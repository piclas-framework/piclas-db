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
"""Readable output of `import --literature`: one block per paper with a status mark (green ✓ fine, yellow ! to check, red ✗ failed,
= already in the store), and at the end the next steps as commands to copy"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import re
import shlex
from dataclasses import dataclass, field
from typing import Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.common.table import paint, use_color
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
    head = f'{paint(mark, tint, color)} {paint(name, "bold" if paper.status != "exists" else "dim", color)} {paper.file}'
    lines = [head]
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


def next_steps(papers: list[Paper], dry_run: bool, color: bool) -> list[str]:
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
        + (' (dry run: nothing copied)' if dry_run else '')
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
    """Collects the papers of one import run and prints a block per paper as it is processed"""

    def __init__(self) -> None:
        self.papers: list[Paper] = []
        self.color = use_color()

    def add(self, paper: Paper) -> None:
        self.papers.append(paper)
        print('\n'.join(block(paper, self.color)))

    def finish(self, dry_run: bool) -> None:
        print('\n'.join(next_steps(self.papers, dry_run, self.color)))
