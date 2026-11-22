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
"""Readable output of `import --literature`: one numbered block per paper with a status mark (green ✓ fine, yellow ! to check, red ✗
failed, ≈ same paper in another file, = already in the store), at the end a table with one line per paper, the next steps as commands
to copy, and optionally a Markdown checklist"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import datetime
import pathlib
import re
import shlex
import shutil
from dataclasses import dataclass, field
from typing import Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.common.table import Row, paint, render, use_color
from piclas_db.sources.doi import Citation, ascii_fold
# ==================================================================================================================================

MARKS = {'ok': ('✓', 'green'), 'check': ('!', 'yellow'), 'error': ('✗', 'red'), 'same': ('≈', 'yellow'), 'exists': ('=', 'dim')}


@dataclass
class Paper:
    file: str
    status: str  # ok, check, error, same (the paper is in the store as another file), exists (this file is in the store)
    key: Optional[str] = None
    cited: Optional[Citation] = None
    message: Optional[str] = None  # error text or the stored file
    checks: list[str] = field(default_factory=list)  # reasons to check
    number: int = 0  # position in the run (1-based), set by the reporter
    total: int = 0
    doi: Optional[str] = None  # given or corrected in the review (else the DOI of cited)
    reference: Optional[str] = None
    key_given: bool = False  # key chosen by the user (kept when the DOI is corrected)

    @property
    def link(self) -> Optional[str]:
        doi = self.doi or (self.cited.doi if self.cited else None)
        return f'https://doi.org/{doi}' if doi else None


def suggested_key(file_name: str) -> str:
    """Key from a file name like 1995-Laux-Direkte-....pdf (rename-papers), else KEY"""
    match = re.match(r'(\d{4})-([A-Za-z][A-Za-z\-]*?)-', ascii_fold(file_name))
    return f'{match.group(2).lower()}-{match.group(1)}' if match else 'KEY'


def classify(file: str, key: str, cited: Citation, automatic_key: bool) -> Paper:
    """Fine, or to check: DOI from a search or a file name, not checked at Crossref, notes, or a key that got a suffix"""
    paper = Paper(file=file, status='ok', key=key, cited=cited)
    if cited.doi_found_in == 'Crossref search':
        paper.checks.append('DOI found by searching Crossref for the first lines of the PDF: open the link and compare title and authors')
    elif cited.doi_found_in == 'file name':
        paper.checks.append('DOI taken from the file name: open the link and compare')
    paper.checks += [note for note in cited.notes if not note.startswith('DOI found by searching')]
    if automatic_key and re.search(r'\d{4}[b-z]$', key):
        paper.checks.append(f'key {key[:-1]} is taken: a second paper of the same first author and year, or the same paper twice?')
    if not cited.doi:
        paper.checks.append('no DOI: the citation is all that identifies the paper')
    if paper.checks:
        paper.status = 'check'
    return paper


def block(paper: Paper, color: bool) -> list[str]:
    mark, tint = MARKS[paper.status]
    name = f'{paper.key or "—":20s}'
    position = paint(f'[{paper.number}/{paper.total}]', 'dim', color) + ' ' if paper.total else ''
    head = f'{position}{paint(mark, tint, color)} {paint(name, "bold" if paper.status != "exists" else "dim", color)} {paper.file}'
    width = min(shutil.get_terminal_size((100, 20)).columns, 120)
    lines = [paint('─' * width, 'dim', color), head]
    cited = paper.cited
    if paper.status == 'exists':
        lines.append(f'      {paint("already in the store: " + str(paper.message), "dim", color)}')
        return lines
    if paper.status == 'same':
        hint = f'not imported; to keep this file as another version: --literature {paper.key} --new-version'
        lines.extend([f'      {paint(str(paper.message), "yellow", color)}', f'      {paint(hint, "dim", color)}'])
        return lines
    if paper.status == 'error':
        lines.append(f'      {paint(str(paper.message), "red", color)}')
        lines.extend(f'      {paint(note, "dim", color)}' for note in (cited.notes if cited else []))
        return lines
    if cited is not None and cited.doi:
        lines.append(f'      DOI   {cited.doi} ({cited.doi_found_in})   {paint(str(cited.link), "blue", color)}')
    if cited is not None and cited.reference:
        lines.append(f'      cite  {cited.reference}' + (' (Crossref)' if cited.reference_from == 'crossref' else ''))
    lines.extend(f'      {paint("check " + reason, "yellow", color)}' for reason in paper.checks)
    return lines


def failed_hint(paper: Paper) -> str:
    """Options for a failed paper: the DOI found in the PDF (Crossref could not confirm it), else placeholders"""
    if paper.cited is not None and paper.cited.doi:
        return f'--doi {paper.cited.doi} --reference "AUTHORS, TITLE, JOURNAL VOLUME:PAGES, YEAR"   # DOI found in the PDF, check it'
    return '--doi DOI   # or --reference "AUTHORS, TITLE, ..., YEAR"'


def quoted(name: str) -> str:
    return shlex.quote(name)


def overview(papers: list[Paper], color: bool) -> list[str]:
    """One line per paper: number, mark, key, DOI and where it was found (or the reason of a failure), file"""
    rows = []
    for paper in papers:
        mark, tint = MARKS[paper.status]
        cited = paper.cited
        if paper.status in ('error', 'same', 'exists'):
            what = str(paper.message or '')
        else:
            doi = paper.doi or (cited.doi if cited else None)
            what = f'{doi} ({cited.doi_found_in})' if doi and cited else 'no DOI: citation only'
        rows.append(Row([str(paper.number), mark, paper.key or '—', what, paper.file], colors=[None, tint, 'bold', None, None]))
    return render(['#', '', 'Key', 'DOI (found in) or reason', 'File'], rows, shrinkable=[3, 4], align_right=(0,), color=color)


def checklist(papers: list[Paper], path: pathlib.Path) -> None:
    """Markdown checklist to tick off while checking the papers (one line per paper with its link)"""
    lines = [f'# Papers to import ({datetime.date.today().isoformat()})', '', 'Marks: ✓ fine, ! to check, ✗ failed, ≈ same paper in the store, = already stored.', '']
    for paper in papers:
        mark = MARKS[paper.status][0]
        done = 'x' if paper.status in ('exists', 'same') else ' '
        link = f' — {paper.link}' if paper.link and paper.status not in ('exists', 'same', 'error') else ''
        reason = f' — {paper.message}' if paper.status in ('error', 'same') else ''
        lines.append(f'- [{done}] {paper.number}. {mark} `{paper.key or "—"}` {paper.file}{link}{reason}')
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def next_steps(papers: list[Paper], dry_run: bool | str, color: bool) -> list[str]:
    counts = {status: sum(p.status == status for p in papers) for status in MARKS}
    summary = (
        f'{len(papers)} paper(s): '
        + paint(f'{counts["ok"]} fine', 'green', color)
        + ', '
        + paint(f'{counts["check"]} to check', 'yellow', color)
        + ', '
        + paint(f'{counts["error"]} failed', 'red', color)
        + (f', {counts["same"]} same paper in another file' if counts['same'] else '')
        + (f', {counts["exists"]} already in the store' if counts['exists'] else '')
        + (' (dry run: nothing copied)' if dry_run is True else f' ({dry_run})' if dry_run else '')
    )
    lines = ['', summary]
    steps: list[list[str]] = []
    checking = [p for p in papers if p.status == 'check']
    if checking:
        steps.append(
            [
                f'Check the {len(checking)} paper(s) marked ! (open the DOI link, compare title, authors and key). A wrong DOI or key: import that file alone, e.g.',
                *[f'    piclas-db import {quoted(p.file)} --literature {p.key} --doi DOI' for p in checking],
            ]
        )
    failed = [p for p in papers if p.status == 'error']
    if failed:
        steps.append(
            [
                f'Import the {len(failed)} failed paper(s) one by one, with the DOI or the citation (books, theses and reports have no DOI):',
                *[f'    piclas-db import {quoted(p.file)} --literature {suggested_key(p.file)} ' + failed_hint(p) for p in failed],
            ]
        )
    same = [p for p in papers if p.status == 'same']
    if same:
        steps.append(
            [
                (
                    f'{len(same)} file(s) marked ≈ are papers already in the store (other download, cover page added or removed). Nothing to do,'
                    ' unless a file is needed as well (e.g. its page numbers match an extraction): keep it as another version with'
                ),
                *[f'    piclas-db import {quoted(p.file)} --literature {p.key} --new-version' for p in same],
            ]
        )
    good = [p for p in papers if p.status in ('ok', 'check')]
    if dry_run and good:
        steps.append(
            [
                f'Import the {len(good)} paper(s) found (move the ones you import alone out of the way first):',
                '    piclas-db import ' + ' \\\n        '.join(quoted(p.file) for p in good) + ' \\\n        --literature',
            ]
        )
    elif not dry_run and good:
        steps.append(['Check keys, DOIs and citations of the store:', '    piclas-db literature list'])
    if steps:
        lines.extend(['', paint('Next steps', 'bold', color)])
        for number, step in enumerate(steps, start=1):
            lines.append(f'{number}. {step[0]}')
            lines.extend(step[1:])
    return lines


class Reporter:
    """Collects the papers of one import run and prints a numbered block per paper as it is processed"""

    def __init__(self, total: int = 0) -> None:
        self.papers: list[Paper] = []
        self.color = use_color()
        self.total = total
        self.paths: list[Optional[pathlib.Path]] = []  # file of each paper (None: not found)

    def add(self, paper: Paper, path: Optional[pathlib.Path] = None) -> None:
        paper.number, paper.total = len(self.papers) + 1, self.total
        self.papers.append(paper)
        self.paths.append(path)
        print('\n'.join(block(paper, self.color)))

    def finish(self, dry_run: bool, steps: bool = True, checklist_file: Optional[str] = None) -> None:
        width = min(shutil.get_terminal_size((100, 20)).columns, 120)
        print(paint('─' * width, 'dim', self.color))
        print('\n'.join(overview(self.papers, self.color)))
        lines = next_steps(self.papers, dry_run if steps else 'nothing copied yet: the review follows', self.color)
        print('\n'.join(lines if steps else lines[:2]))
        if checklist_file:
            checklist(self.papers, pathlib.Path(checklist_file))
            print(f'Checklist: {checklist_file}')
