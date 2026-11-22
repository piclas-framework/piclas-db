# ==================================================================================================================================
# Copyright (c) 2026 Stephen Copplestone and the piclas-db contributors (see CONTRIBUTORS.md)
#
# This file is part of piclas-db (github.com/piclas-framework/piclas-db). piclas-db is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3
# of the License, or (at your option) any later version.
#
# piclas-db is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License v3.0 for more details.
#
# You should have received a copy of the GNU General Public License along with piclas-db. If not, see <https://www.gnu.org/licenses/>.
# ==================================================================================================================================
# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import argparse
import datetime
import pathlib
from typing import Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.literature import papers
from piclas_db.commands.paper_report import Paper, Reporter, classify
from piclas_db.common.spinner import Progress
from piclas_db.sources.doi import paper_citation
from piclas_db.sources.identify import IdentifyError, identify
from piclas_db import config, wanted
from piclas_db.git import GitError
from piclas_db.resolve import store_status
from piclas_db.build import lxcat_index
from piclas_db.sources.lxcat import fingerprint, load_lxcat
from piclas_db.store import Store, StoreEntry, sha256
# ==================================================================================================================================


def candidate_files(args: argparse.Namespace) -> list[tuple[pathlib.Path, bool]]:
    """Files to import and whether they were given explicitly (errors) or found in --source-dir (skipped if unknown)"""
    files = [(pathlib.Path(name), True) for name in args.files]
    if args.source_dir:
        directory = pathlib.Path(args.source_dir).expanduser()
        if not directory.is_dir():
            raise FileNotFoundError(f'source directory not found: {directory}')
        files += [(path, False) for path in sorted(directory.rglob('*')) if path.is_file() and not any(part.startswith('.') for part in path.parts)]
    return files


def parse_date(text: Optional[str]) -> Optional[datetime.date]:
    return datetime.date.fromisoformat(text) if text else None


def lxcat_news(store: Store, entry: StoreEntry) -> str:
    """What a new LXCat download adds to the processes already in the store (downloads grow: Elastic first, Ionization later)"""
    known: dict[tuple[str, str, str], set[str]] = {}
    for process, _, other in lxcat_index(store):
        if other.relative != entry.relative:
            database, species, name, updated = fingerprint(process)
            known.setdefault((database, species, name), set()).add(updated)
    new = updated_count = present = 0
    for process in load_lxcat(entry.path).processes:
        database, species, name, updated = fingerprint(process)
        if (database, species, name) not in known:
            new += 1
        elif updated not in known[(database, species, name)]:
            updated_count += 1
        else:
            present += 1
    return f'{new} new process(es), {updated_count} with a newer or other update time, {present} already in the store'


def run(args: argparse.Namespace) -> int:
    """Identify downloaded files by their content, validate them and copy them into the local store"""
    store = Store(args.store)
    try:
        files = candidate_files(args)
        retrieved = parse_date(args.retrieved)
        by = None if args.dry_run else config.require_identity()
    except (FileNotFoundError, ValueError, config.ConfigError) as e:
        print(f'ERROR: {e}')
        return 1
    if not files:
        print('Nothing to import (give files or --source-dir)')
        return 1
    if args.literature and len(files) > 1:  # one key (and DOI, citation) for several papers would store them all as one paper
        print('ERROR: --literature KEY, --doi and --reference are for one paper; import several papers with --literature alone (keys from Crossref)')
        return 1
    if args.literature is not None and len(files) > 1 and (args.doi or args.reference):
        print('ERROR: --doi and --reference are for one paper; import several papers with --literature alone (keys from Crossref)')
        return 1

    print(f'Store: {store.root}' + (' (dry run, nothing is copied)' if args.dry_run else ''))
    papers_mode = args.literature is not None
    reporter = Reporter() if papers_mode else None
    imported = existing = skipped = failed = 0
    taken: set[str] = set()  # keys given to papers of this run
    progress = Progress(len(files)) if papers_mode else None
    for number, (path, explicit) in enumerate(files):
        if not path.is_file():
            if reporter:
                reporter.add(Paper(file=str(path), status='error', message='file not found'))
            else:
                print(f'  ERROR    {path}: file not found')
            failed += 1
            continue
        stored = store.find(sha256(path)) if reporter else None
        if reporter and stored is not None:  # the same paper (same sha256) is in the store: no lookup, no key needed
            reporter.add(Paper(file=str(path), status='exists', key=str(stored.meta.get('dataset')), message=str(stored.relative)))
            existing += 1
            continue
        doi, reference, cited, key = args.doi, args.reference, None, args.literature
        if args.literature is not None and path.suffix.lower() == '.pdf':
            assert progress is not None
            with progress.step(number, f'{path.name}: DOI and citation (Crossref)'):
                cited = paper_citation(path, args.doi, args.reference, lookup=not args.no_lookup)
            doi, reference = cited.doi, cited.reference
            if not (doi or reference):
                assert reporter is not None
                reporter.add(Paper(file=str(path), status='error', cited=cited, message='DOI and citation not found: give --doi or --reference'))
                failed += 1
                continue
            if not key:
                key = cited.key(set(papers(store)) | taken)
                if key is None:
                    assert reporter is not None
                    reporter.add(Paper(file=str(path), status='error', cited=cited, message='no key: first author and year unknown (no Crossref record); give --literature KEY'))
                    failed += 1
                    continue
                taken.add(key)
        elif args.literature == '':
            key = 'paper'  # not a PDF: identify reports it
        try:
            identified = identify(path, species=args.species, custom=args.custom, literature=key if args.literature is not None else None, doi=doi, reference=reference)
            if cited is not None:
                identified.details.update({'doi_found_in': cited.doi_found_in, 'reference_from': cited.reference_from})
        except IdentifyError as e:
            if reporter:
                reporter.add(Paper(file=str(path), status='error', key=key or None, cited=cited, message=str(e)))
                failed += 1
            elif explicit:
                print(f'  ERROR    {path}: {e}')
                failed += 1
            else:
                print(f'  skipped  {path}: {e}')
                skipped += 1
            continue

        duplicate = store.find(sha256(path))
        if duplicate is not None:
            if reporter:
                reporter.add(Paper(file=str(path), status='exists', key=str(duplicate.meta.get('dataset')), message=str(duplicate.relative)))
            else:
                print(f'  exists   {path} -> {duplicate.relative}')
            existing += 1
            continue
        label = f'{identified.provider}' + (f' {identified.kind}' if identified.kind != identified.provider else '') + f': {identified.dataset}'
        if identified.retrieved is None and retrieved is None and identified.provider != 'literature':  # papers: date means little
            label += ' (retrieval date unknown, use --retrieved YYYY-MM-DD)'
        if args.dry_run:
            if reporter and cited is not None:
                reporter.add(classify(str(path), identified.dataset, cited, automatic_key=not args.literature))
            else:
                print(f'  would import {path} ({label})')
        else:
            try:
                entry = store.add(path, identified, retrieved=retrieved, by=by)
            except GitError as e:
                print(f'  ERROR    {path}: copied into the store but not committed: {e}')
                failed += 1
                continue
            if reporter and cited is not None:
                reporter.add(classify(str(path), identified.dataset, cited, automatic_key=not args.literature))
                print(f'      stored {entry.relative}')
            else:
                print(f'  imported {path} -> {entry.relative} ({label})')
            if identified.provider == 'literature':
                found_doi = identified.details.get('doi')
                for name in wanted.fulfilled(store, identified.dataset, str(found_doi) if found_doi else None):
                    print(f'      wanted list: {name} no longer wanted')
            if identified.provider == 'lxcat' and identified.kind == 'cross-sections':
                print(f'           {lxcat_news(store, entry)}')
        imported += 1

    if reporter:
        reporter.finish(args.dry_run)
    else:
        print(f'{imported} {"would be imported" if args.dry_run else "imported"}, {existing} already in the store, {skipped} skipped, {failed} failed')
    if not args.dry_run and store.root.is_dir():
        print(f'Store: {store_status(store)}')
    return 1 if failed else 0
