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
"""Tables from PDF files ('piclas-db extract --table')

Words with their positions come from the text layer of the PDF, or from OCR (Tesseract) for scanned pages. The table is found by its
caption ('TABLE 12.', 'Table 2:'), above or below it; on two-column pages only the column of the caption is used. Columns are
separated where no word of a data row lies; cells are the words of a column in a row. Numbers are read in the notations of papers:
'9.70E−07', '9.5185(-4)' (= 9.5185e-4), '0.003 51' (digit groups), footnote marks are removed. A table that continues on the next
page ('—Continued') is joined.
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Any, Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.extract.vector import ExtractError, require_pdfplumber
# ==================================================================================================================================

MINUS = str.maketrans({'−': '-', '–': '-', '—': '-', '\u2009': '', '\u202f': '', '\xa0': ''})
NUMBER = re.compile(r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+|\([-+]?\d+\))?')


@dataclass
class Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float


@dataclass
class Table:
    number: str
    caption: str
    pages: list[int]
    header: list[str]  # one text per column
    rows: list[list[str]] = field(default_factory=list)
    source: str = 'text'  # 'text' or 'ocr'


def parse_number(text: str) -> Optional[float]:
    """Number in the notations of papers, None for anything else ('-', labels)"""
    cleaned = text.translate(MINUS).replace(' ', '').rstrip('*∗†‡abcd').replace('(cid:1)', '').replace('(cid:2)', '')
    if not cleaned or not NUMBER.fullmatch(cleaned):
        return None
    match = re.fullmatch(r'(.+)\(([-+]?\d+)\)', cleaned)
    if match:
        return float(match.group(1)) * 10.0 ** int(match.group(2))
    return float(cleaned)


# ----------------------------------------------------------------------------------------------------------------------------------
# Words
# ----------------------------------------------------------------------------------------------------------------------------------
def text_words(page: Any) -> list[Word]:
    return [Word(w['text'], w['x0'], w['x1'], w['top'], w['bottom']) for w in page.extract_words(keep_blank_chars=False, x_tolerance=1.5)]


def ocr_words(page: Any) -> list[Word]:
    """Words of a scanned page by OCR, coordinates in pt"""
    if shutil.which('tesseract') is None:
        raise ExtractError('the page has no text layer and Tesseract is not installed for OCR')
    resolution = 400
    scale = resolution / 72
    with tempfile.NamedTemporaryFile(suffix='.png') as file:
        page.to_image(resolution=resolution).original.save(file.name)
        tsv = subprocess.run(['tesseract', file.name, '-', '--psm', '6', 'tsv'], capture_output=True, text=True, check=False).stdout
    words = []
    for line in tsv.splitlines()[1:]:
        fields = line.split('\t')
        if len(fields) == 12 and fields[11].strip() and float(fields[10]) > 0:
            left, top, width, height = (int(fields[i]) / scale for i in (6, 7, 8, 9))
            words.append(Word(fields[11].strip(), left, left + width, top, top + height))
    return words


def lines_of(words: list[Word]) -> list[list[Word]]:
    """Words grouped into lines (by their vertical centre), each line sorted from left to right"""
    lines: list[list[Word]] = []
    for word in sorted(words, key=lambda w: (w.top + w.bottom) / 2):
        centre = (word.top + word.bottom) / 2
        if lines and abs(centre - sum((w.top + w.bottom) / 2 for w in lines[-1]) / len(lines[-1])) < 0.45 * (word.bottom - word.top):
            lines[-1].append(word)
        else:
            lines.append([word])
    return [sorted(line, key=lambda w: w.x0) for line in lines]


def column_of_caption(words: list[Word], caption: Word, width: float) -> list[Word]:
    """On a two-column page (no word crosses the middle) only the words of the caption's column"""
    middle = width / 2
    # judged near the caption only: figures or headings elsewhere on the page may cross the middle
    near = [w for w in words if caption.top - 250 < w.top < caption.top + 250]
    crossing = sum(1 for w in near if w.x0 < middle - 2 < middle + 2 < w.x1)
    if crossing > 0.02 * len(near):
        return words
    left = caption.x0 < middle
    return [w for w in words if (w.x1 <= middle + 2) == left]


# ----------------------------------------------------------------------------------------------------------------------------------
# Table
# ----------------------------------------------------------------------------------------------------------------------------------
def numeric_count(line: list[Word]) -> int:
    return sum(1 for word in line if parse_number(word.text) is not None)


def tabular(line: list[Word]) -> bool:
    """Data row: at least two numbers, and numbers are the majority of the words (header lines like 'n = 2' are not data)"""
    count = numeric_count(line)
    return count >= 2 and count >= 0.5 * len(line)


def find_captions(words: list[Word], number: str) -> list[tuple[Word, str]]:
    """Possible captions of table <number> ('TABLE12.', 'TABLE 12.', 'Table 2:') with the text of their line; references in
    the running text ('as shown in Table 7.') are candidates too and are discarded when no table follows them"""
    pattern = re.compile(rf'^(TABLE|Table)\s*{re.escape(number)}[.:]?$')
    found = []
    for index, word in enumerate(words):
        if pattern.match(word.text) or (word.text in ('TABLE', 'Table') and index + 1 < len(words) and re.fullmatch(rf'{re.escape(number)}[.:]?', words[index + 1].text)):
            line = [w for w in words if abs((w.top + w.bottom) / 2 - (word.top + word.bottom) / 2) < 3 and w.x0 >= word.x0 - 1]
            found.append((word, ' '.join(w.text for w in sorted(line, key=lambda w: w.x0))))
    # upper-case captions ('TABLE') first: they are captions, 'Table' may also be a reference in the text
    return sorted(found, key=lambda item: item[0].text.startswith('Table'))


def block(lines: list[list[Word]], start: int, step: int) -> list[list[Word]]:
    """Consecutive lines of a table from 'start' in direction 'step' (+1 down, -1 up); header lines on the caption side are included"""
    selected: list[list[Word]] = []
    index = start
    spacing: Optional[float] = None  # smallest line distance within the data
    data_started = False
    while 0 <= index < len(lines):
        line = lines[index]
        if selected:
            gap = abs(line[0].top - selected[-1][0].top)
            limit = 2.6 * spacing if spacing is not None else 40.0  # header lines may be spaced unevenly
            if gap > limit:
                break
            if data_started and tabular(line) and tabular(selected[-1]):
                spacing = gap if spacing is None else min(spacing, gap)
        if tabular(line):
            data_started = True
        elif data_started:
            # a text line after the data: the table ended (going down), or the header line (going up, then the table ends)
            if step > 0:
                break
            # header going up: one or two close lines (symbols such as arrows may sit on a line of their own)
            headers = [entry for entry in selected if not tabular(entry)]
            if len(headers) >= 2 or (headers and abs(line[0].top - selected[-1][0].top) > 12.0):
                break
        elif len(selected) > 6:
            break
        selected.append(line)
        index += step
    return selected if step > 0 else list(reversed(selected))


def columns(data: list[list[Word]]) -> list[tuple[float, float]]:
    """Column x-ranges: gaps in the union of the words of all data lines"""
    spans = sorted((w.x0, w.x1) for line in data for w in line)
    merged: list[list[float]] = []
    for x0, x1 in spans:
        if merged and x0 <= merged[-1][1] + 2.0:
            merged[-1][1] = max(merged[-1][1], x1)
        else:
            merged.append([x0, x1])
    return [(a, b) for a, b in merged]


def cells(line: list[Word], ranges: list[tuple[float, float]]) -> list[str]:
    result = [''] * len(ranges)
    for word in line:
        centre = (word.x0 + word.x1) / 2
        index = min(range(len(ranges)), key=lambda i: 0.0 if ranges[i][0] - 1 <= centre <= ranges[i][1] + 1 else min(abs(centre - ranges[i][0]), abs(centre - ranges[i][1])))
        result[index] = (result[index] + ' ' + word.text).strip() if result[index] else word.text
    # digit groups of one number ('0.003 51') are joined
    return [re.sub(r'(?<=\d) (?=\d)', '', cell) for cell in result]


def table_on_page(page: Any, number: str, use_ocr: bool) -> Optional[Table]:
    words = [] if use_ocr else text_words(page)
    source = 'text'
    if not words:
        words, source = ocr_words(page), 'ocr'
    all_words = words
    caption_text = ''
    for caption, candidate_text in find_captions(all_words, number):
        caption_text = candidate_text
        words = column_of_caption(all_words, caption, float(page.width))
        lines = lines_of(words)
        caption_line = next(i for i, line in enumerate(lines) if caption in line)
        below = block(lines, caption_line + 1, +1)
        above = block(lines, caption_line - 1, -1)
        rows = below if sum(tabular(line) for line in below) >= sum(tabular(line) for line in above) else above
        if sum(tabular(line) for line in rows) >= 2:
            break
    else:
        return None
    data = [line for line in rows if tabular(line)]
    ranges = columns(data)
    header_lines = [line for line in rows if not tabular(line)]
    header = [' '.join(part for part in parts if part) for parts in zip(*(cells(line, ranges) for line in header_lines), strict=False)] if header_lines else [''] * len(ranges)
    header += [''] * (len(ranges) - len(header))
    body = [cells(line, ranges) for line in data]
    # a label split into two columns (e.g. '∆E(eV' and ')'): columns without any number are joined to a label column on the left
    index = 1
    while index < len(header):
        if all(parse_number(row[index]) is None for row in body) and all(parse_number(row[index - 1]) is None for row in body):
            header[index - 1] = f'{header[index - 1]} {header[index]}'.strip()
            for row in body:
                row[index - 1] = f'{row[index - 1]} {row[index]}'.strip()
                del row[index]
            del header[index]
        else:
            index += 1
    return Table(number, caption_text, [page.page_number], header, body, source)


def extract_table(path: str, pages: list[int], number: str, use_ocr: bool = False) -> Table:
    """Table <number> on the given pages; continuations on following pages are joined"""
    pdfplumber = require_pdfplumber()
    table: Optional[Table] = None
    with pdfplumber.open(path) as pdf:
        for page_number in pages:
            if not 1 <= page_number <= len(pdf.pages):
                raise ExtractError(f'page {page_number} does not exist ({len(pdf.pages)} pages)')
            part = table_on_page(pdf.pages[page_number - 1], number, use_ocr)
            if part is None:
                continue
            if table is None:
                table = part
            elif len(part.rows[0]) == len(table.rows[0]):
                table.rows.extend(part.rows)
                table.pages.extend(part.pages)
            else:
                raise ExtractError(f'continuation of table {number} on page {page_number} has {len(part.rows[0])} instead of {len(table.rows[0])} columns')
    if table is None:
        raise ExtractError(f'table {number} not found on page(s) {", ".join(str(p) for p in pages)}')
    return table


# ----------------------------------------------------------------------------------------------------------------------------------
# Units from the header
# ----------------------------------------------------------------------------------------------------------------------------------
def header_unit(text: str) -> Optional[str]:
    """Unit in a column header: '(eV)' -> 'eV', '(10−17cm2)' -> '1e-17 cm^2', 'Å2' -> 'A^2'"""
    cleaned = text.translate(MINUS).replace('(cid:1)', '(').replace('(cid:2)', ')').replace(' ', '')
    match = re.search(r'10\^?(-?\d+)(cm\^?2|m\^?2|[ÅA]\^?2)', cleaned)
    if match:
        area = {'cm': 'cm^2', 'm': 'm^2'}.get(match.group(2).rstrip('^2').rstrip('2').rstrip('^'), 'A^2')
        return f'1e{match.group(1)} {area}'
    for pattern, unit in ((r'\(k?eV\)', None), (r'cm\^?2', 'cm^2'), (r'[ÅA]\^?2', 'A^2')):
        found = re.search(pattern, cleaned)
        if found:
            return unit or found.group(0).strip('()')
    return None
