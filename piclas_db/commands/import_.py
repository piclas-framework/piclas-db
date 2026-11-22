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
import sys
from collections.abc import Callable
from typing import Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.literature import papers
from piclas_db.commands.paper_report import Paper, Reporter, classify
from piclas_db.commands.paper_review import review
from piclas_db.common.spinner import Progress
from piclas_db.sources.doi import paper_citation
from piclas_db.sources.same_paper import SamePaper, pages
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


def importer(store: Store, by: Optional[str], same_papers: Optional[SamePaper]) -> Callable[[pathlib.Path, Paper], str]:
    """Stores one paper of a review with the key, DOI and citation decided there"""

    def store_paper(path: pathlib.Path, paper: Paper) -> str:
        cited = paper.cited
        doi = paper.doi or (cited.doi if cited else None)
        reference = paper.reference or (cited.reference if cited else None)
        try:
            identified = identify(path, literature=paper.key, doi=doi, reference=reference)
            if cited is not None:
                identified.details.update({'doi_found_in': 'given' if paper.doi else cited.doi_found_in, 'reference_from': 'given' if paper.reference else cited.reference_from})
            entry = store.add(path, identified, by=by)
        except (IdentifyError, GitError) as e:
            raise ValueError(str(e)) from e
        if same_papers is not None:
            same_papers.papers.append(entry)
        for name in wanted.fulfilled(store, identified.dataset, doi):
            print(f'      wanted list: {name} no longer wanted')
        return str(entry.relative)

    return store_paper


def run(args: argparse.Namespace) -> int:
    """Identify downloaded files by their content, validate them and copy them into the local store"""
    store = Store(args.store)
    try:
        files = candidate_files(args)
        retrieved = parse_date(args.retrieved)
        by = None if args.dry_run and not args.review else config.require_identity()
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

    papers_mode = args.literature is not None
    if (args.review or args.checklist) and not papers_mode:
        print('ERROR: --review and --checklist are for papers (--literature)')
        return 1
    if args.review and not sys.stdin.isatty():
        print('ERROR: --review asks questions: run it in a terminal (or use --dry-run and --checklist)')
        return 1
    dry_run = args.dry_run or args.review  # a review looks up all papers first and stores them one by one afterwards
    print(f'Store: {store.root}' + (' (review: all papers are looked up first, then decided one by one)' if args.review else ' (dry run, nothing is copied)' if args.dry_run else ''))
    reporter = Reporter(total=len(files)) if papers_mode else None
    imported = existing = skipped = failed = same = 0
    same_papers: Optional[SamePaper] = None  # stored papers with their texts, read once per run
    taken: set[str] = set()  # keys given to papers of this run
    progress = Progress(len(files)) if papers_mode else None
    for number, (path, explicit) in enumerate(files):
        if not path.is_file():
            if reporter:
                reporter.add(Paper(file=str(path), status='error', message='file not found'), None)
            else:
                print(f'  ERROR    {path}: file not found')
            failed += 1
            continue
        stored = store.find(sha256(path)) if reporter else None
        if reporter and stored is not None:  # the same paper (same sha256) is in the store: no lookup, no key needed
            reporter.add(Paper(file=str(path), status='exists', key=str(stored.meta.get('dataset')), message=str(stored.relative)), path)
            existing += 1
            continue
        doi, reference, cited, key = args.doi, args.reference, None, args.literature
        if args.literature is not None and path.suffix.lower() == '.pdf':
            assert progress is not None
            with progress.step(number, f'{path.name}: DOI and citation (Crossref)'):
                cited = paper_citation(path, args.doi, args.reference, lookup=not args.no_lookup)
            doi, reference = cited.doi, cited.reference
            assert reporter is not None
            if same_papers is None:
                same_papers = SamePaper(store)
            with progress.step(number, f'{path.name}: compared with the papers in the store'):
                match = same_papers.find(path, doi)
            if match is not None and not args.new_version:
                info = f'same paper as {match.key} ({match.reason}), other file: {pages(path)} instead of {pages(match.entry.path)} pages'
                reporter.add(Paper(file=str(path), status='same', key=match.key, cited=cited, message=info), path)
                same += 1
                continue
            if match is not None:  # --new-version: another file of a stored paper, under its key, with its citation if none was found
                if args.literature and args.literature != match.key:
                    print(f'WARNING: {path} is the same paper as {match.key}: stored under {match.key}, not {args.literature}')
                key = match.key
                doi = doi or match.entry.meta.get('doi')
                reference = reference or match.entry.meta.get('reference')
            if not (doi or reference):
                reporter.add(Paper(file=str(path), status='error', cited=cited, message='DOI and citation not found: give --doi or --reference'), path)
                failed += 1
                continue
            if not key:
                key = cited.key(set(papers(store)) | taken)
                if key is None:
                    reporter.add(Paper(file=str(path), status='error', cited=cited, message='no key: first author and year unknown (no Crossref record); give --literature KEY'), path)
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
                reporter.add(Paper(file=str(path), status='error', key=key or None, cited=cited, message=str(e)), path)
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
                reporter.add(Paper(file=str(path), status='exists', key=str(duplicate.meta.get('dataset')), message=str(duplicate.relative)), path)
            else:
                print(f'  exists   {path} -> {duplicate.relative}')
            existing += 1
            continue
        label = f'{identified.provider}' + (f' {identified.kind}' if identified.kind != identified.provider else '') + f': {identified.dataset}'
        if identified.retrieved is None and retrieved is None and identified.provider != 'literature':  # papers: date means little
            label += ' (retrieval date unknown, use --retrieved YYYY-MM-DD)'
        if dry_run:
            if reporter and cited is not None:
                reporter.add(classify(str(path), identified.dataset, cited, automatic_key=not args.literature), path)
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
                reporter.add(classify(str(path), identified.dataset, cited, automatic_key=not args.literature), path)
                print(f'      stored {entry.relative}')
                if same_papers is not None:
                    same_papers.papers.append(entry)  # later files of this run are compared with it too
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
        reporter.finish(dry_run, steps=not args.review, checklist_file=args.checklist)
        if args.review:
            review(reporter.papers, reporter.paths, lambda path, doi, reference: paper_citation(path, doi, reference, lookup=not args.no_lookup), importer(store, by, same_papers), taken, reporter.color)
            return 0
    else:
        print(f'{imported} {"would be imported" if args.dry_run else "imported"}, {existing} already in the store, {skipped} skipped, {failed} failed')
    if not args.dry_run and store.root.is_dir():
        print(f'Store: {store_status(store)}')
    return 1 if failed else 0
