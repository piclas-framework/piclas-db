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
"""Interactive review of the papers of `import --literature --review`, after the overview: one paper at a time, open its DOI link,
import it, correct key, DOI or citation (looked up again), skip it or stop. Decisions are remembered in .piclas-db-review.yaml of the
current directory, so a later review continues with the papers not decided yet; imported papers are in the store anyway.

With --dry-run nothing is stored: `y` approves the paper with its key, DOI and citation, and the next review without --dry-run imports
the approved papers first, without asking again ("decide now, import later")."""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import pathlib
import re
import shutil
import subprocess
import sys
import urllib.parse
import webbrowser
from collections.abc import Callable
from typing import Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import yaml

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.commands.paper_report import Paper, block, classify
from piclas_db.common.table import paint
from piclas_db.sources.doi import Citation
from piclas_db.store import sha256
# ==================================================================================================================================

SESSION = '.piclas-db-review.yaml'
HELP = """  o         open the DOI link in the browser (without DOI: a Google Scholar search for the file name)
  p         open the PDF
  y         import this paper (key, DOI and citation as shown; with --dry-run: approve it for a later import)
  k KEY     use another key            d DOI      use this DOI (looked up again)
  r TEXT    use this citation          s          skip (remembered for the next review)
  q         stop (continue later with the same command)       ?   this help"""

Lookup = Callable[[pathlib.Path, Optional[str], Optional[str]], Citation]
Importer = Callable[[pathlib.Path, Paper], str]  # stores the paper, returns the stored file (raises ValueError with the reason)


def open_link(target: str) -> None:
    """Open a URL or file in the desktop's browser or viewer, detached and silent (browsers write log lines to the terminal)"""
    opener = 'open' if sys.platform == 'darwin' else shutil.which('xdg-open')
    if opener:
        try:
            subprocess.Popen([opener, target], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)  # noqa: S603 (fixed opener)
            return
        except OSError:
            pass
    webbrowser.open(target)


def scholar(path: pathlib.Path) -> str:
    """Google Scholar search for a paper without DOI: the words of its file name (year, author and title in names like
    2008-Lofthouse-Nonequilibrium-Hypersonic-....pdf)"""
    words = ' '.join(re.split(r'[_\-\s]+', path.stem))
    return 'https://scholar.google.com/scholar?' + urllib.parse.urlencode({'q': words})


def load_session(directory: pathlib.Path) -> dict[str, dict]:
    path = directory / SESSION
    try:
        data = yaml.safe_load(path.read_text(encoding='utf-8')) if path.is_file() else {}
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def save_session(directory: pathlib.Path, session: dict[str, dict]) -> None:
    path = directory / SESSION
    if session:
        path.write_text(yaml.safe_dump(session, sort_keys=True, allow_unicode=True), encoding='utf-8')
    elif path.exists():
        path.unlink()


def review(
    papers: list[Paper],
    paths: list[Optional[pathlib.Path]],
    lookup: Lookup,
    importer: Importer,
    taken: set[str],
    color: bool,
    ask: Optional[Callable[[str], str]] = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Walk through the papers still to decide; returns the counts of imported, approved, skipped and open papers"""
    ask = ask or input  # looked up at call time (tests replace builtins.input)
    directory = pathlib.Path.cwd()
    session = load_session(directory)
    counts = {'imported': 0, 'approved': 0, 'skipped': 0, 'open': 0}
    candidates = [(paper, path) for paper, path in zip(papers, paths, strict=True) if path is not None and paper.status in ('ok', 'check', 'error')]
    imported_now: set[str] = set()
    approved_earlier = [(paper, path) for paper, path in candidates if session.get(sha256(path), {}).get('decision') == 'approved']
    if approved_earlier and not dry_run:  # approved in a dry-run review: imported now, without asking again
        print()
        print(paint(f'Importing {len(approved_earlier)} paper(s) approved in an earlier dry-run review', 'bold', color))
        for paper, path in approved_earlier:
            entry = session.pop(sha256(path))
            paper.key, paper.doi, paper.reference, paper.key_given = entry.get('key') or paper.key, entry.get('doi'), entry.get('reference'), True
            try:
                stored = importer(path, paper)
            except ValueError as e:
                print(paint(f'  ERROR {paper.file}: {e} (asked again below)', 'red', color))
                continue
            print(paint(f'  {paper.key}: imported -> {stored}', 'green', color))
            imported_now.add(sha256(path))
            counts['imported'] += 1
    decisions = {sha256(path): session.get(sha256(path), {}).get('decision') for _, path in candidates}
    earlier = [item for item in candidates if decisions[sha256(item[1])] == 'skipped']
    approved = [item for item in candidates if decisions[sha256(item[1])] == 'approved']  # only left in a dry run
    pending = [item for item in candidates if decisions[sha256(item[1])] is None and sha256(item[1]) not in imported_now]
    print()
    print(
        paint(f'Review{" (dry run: y approves, nothing is stored)" if dry_run else ""}: {len(pending)} paper(s) to decide', 'bold', color)
        + (f', {len(earlier)} skipped earlier' if earlier else '')
        + (f', {len(approved)} approved earlier' if approved and dry_run else '')
        + '  (? for help)'
    )
    for index, (paper, path) in enumerate(pending):
        print('\n'.join(block(paper, color)))
        while True:
            answer = ask(paint(f'  [{index + 1}/{len(pending)}] o open link, p pdf, y import, k key, d doi, r citation, s skip, q quit > ', 'bold', color)).strip()
            command, _, value = answer.partition(' ')
            command, value = command.lower(), value.strip()
            if command == 'q':
                counts['open'] = len(pending) - index
                save_session(directory, session)
                print(f'Stopped: {counts["open"]} paper(s) left; the same command continues with them.')
                return counts
            if command in ('?', 'h', 'help', ''):
                print(HELP)
            elif command == 'o':
                link = paper.link or scholar(path)
                open_link(link)
                print(f'  opened {link}' + ('' if paper.link else ' (no DOI: search for the title; books and theses: give the citation with r)'))
            elif command == 'p':
                open_link(str(path.resolve()))
                print(f'  opened {path.name}')
            elif command == 's':
                session[sha256(path)] = {'decision': 'skipped', 'file': path.name}
                counts['skipped'] += 1
                break
            elif command == 'k':
                key = value or ask('  key: ').strip()
                if key:
                    paper.key, paper.key_given = key, True
                    print('\n'.join(block(paper, color)))
            elif command in ('d', 'r'):
                text = value or ask('  DOI: ' if command == 'd' else '  citation: ').strip()
                if not text:
                    continue
                if command == 'd':
                    paper.doi = text
                else:
                    paper.reference = text
                cited = lookup(path, paper.doi, paper.reference)
                key = paper.key if paper.key_given else (cited.key(taken) or paper.key)
                updated = classify(paper.file, key or 'KEY', cited, automatic_key=not paper.key_given) if (cited.doi or cited.reference) else None
                if updated is None:
                    paper.message = 'DOI and citation not found'
                else:
                    updated.number, updated.total, updated.doi, updated.reference, updated.key_given = paper.number, paper.total, paper.doi, paper.reference, paper.key_given
                    paper.__dict__.update(updated.__dict__)
                    if paper.key:
                        taken.add(paper.key)
                print('\n'.join(block(paper, color)))
            elif command == 'y':
                if paper.status == 'error' or not paper.key:
                    print(paint('  not importable yet: give a DOI (d) or a citation (r), and a key (k)', 'red', color))
                    continue
                if dry_run:
                    cited = paper.cited
                    session[sha256(path)] = {
                        'decision': 'approved',
                        'file': path.name,
                        'key': paper.key,
                        'doi': paper.doi or (cited.doi if cited else None),
                        'reference': paper.reference or (cited.reference if cited else None),
                    }
                    print(paint(f'  approved as {paper.key} (imported by the next review without --dry-run)', 'green', color))
                    counts['approved'] += 1
                    break
                try:
                    stored = importer(path, paper)
                except ValueError as e:
                    print(paint(f'  ERROR {e}', 'red', color))
                    continue
                print(paint(f'  imported -> {stored}', 'green', color))
                session.pop(sha256(path), None)
                counts['imported'] += 1
                break
            else:
                print('  unknown answer (? for help)')
    save_session(directory, session)
    done = f'{counts["approved"]} approved (import them: the same command without --dry-run)' if dry_run else f'{counts["imported"]} imported'
    print(f'Review done: {done}, {counts["skipped"]} skipped' + (f', {len(earlier)} skipped earlier (delete {SESSION} to review them again)' if earlier else ''))
    return counts
