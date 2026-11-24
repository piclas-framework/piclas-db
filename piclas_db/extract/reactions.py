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
"""Reaction tables with columns (C, n, T_d, controlling temperature, third body in columns of their own, e.g. Park 1993/1994/2001,
Johnston 2014, Laux 1995, Gökçen 2007): rows of words -> raw copy (cells under the column headers) and rate rows.

Rows are read from words with positions (text layer, the character-level reader of table.py, or OCR): a row with a reaction arrow
starts a reaction; rows without one but with values (third-body sub-rows: Park's M = N, O, N2, ..., Johnston's Ar / Others, Gökçen's
'Enhanced rate for M = N, C, H') belong to the reaction above and take the values they do not print from its first row. Value
words are assigned to the column whose header they sit under; the role of a column (C, n, T_d, Tx, third body) comes from its
header, refined by its content (temperatures like √TTv are the controlling temperature, numbers above 100 the activation
temperature), or from --columns. Tables printed in two halves side by side (Park 2001) are read left half first."""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import re
from dataclasses import dataclass, field
from typing import Any, Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.extract.table import Word
from piclas_db.rates import Converted, RateError, convert_reaction, parse_number, parse_rate, printed_species
# ==================================================================================================================================

ARROWS = '→⇌↔⇔⇄'
ROLES = ('label', 'reaction', 'M', 'C', 'n', 'Td', 'Tx', 'formula', 'skip')
CONTROLLING = {'t': 'T', 'ta': 'Ta', 'tv': 'Tv', 'te': 'Te', 'tve': 'Tve', 'ttr': 'Ttr', 'tr': 'Ttr', '√ttv': 'Ta', 'ttv': 'Ta', 'tetv': 'Tve'}


@dataclass
class Column:
    header: str
    x0: float
    x1: float
    role: str = 'skip'

    @property
    def centre(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class Result:
    header: list[str]
    raw: list[list[str]] = field(default_factory=list)  # cells under the column headers, as printed
    converted: list[Converted] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def plain(text: str) -> str:
    return re.sub(r'[^a-z0-9√,\[\]/()]', '', text.lower().replace('−', '-'))


def header_role(text: str) -> str:
    """Role of a column by its header: 'A, cc/mol/s' -> C, 'nf;i' -> n, 'Df;i' -> Td, 'Tf;i' -> Tx, 'Third body, M' -> M, ..."""
    key = plain(text)
    if '=' in text and not text.strip().lower().startswith(('a,', 'a ')):
        return 'skip'  # a formula above the columns ('kf = AT^n e^-Ta/T', Gökçen 2007)
    if key in ('i', 'nr', 'nr.', 'no', 'number', '#'):
        return 'label'
    if key.startswith(('ref', 'source', 'fi', 'ef')):
        return 'skip'
    if key.startswith('reaction') or 'reaktion' in key:
        return 'reaction'
    if key == 'm' or key.startswith('thirdbody'):
        return 'M'
    if key.startswith(('ratecoeff', 'rate')) or key in ('k', 'kf', 'k(t)'):
        return 'formula'  # the whole rate coefficient in one cell: 1.162×10−8 T−1.6 exp(-113 200/T)
    if key.startswith(('af', 'ab', 'a,', 'a[', 'c')) or key in ('a', 'c', 'cc/mol/s'):
        return 'C'
    if key.startswith(('nf', 'bf', 'bb')) or key in ('n', 'b'):
        return 'n'
    if key.startswith(('df', 'ea', 'eb', 'tr', 'td', 'θ')) or key in ('ta,k', 'tak'):
        return 'Td'
    if key.startswith(('tf', 'tx')) or key == 'ta':
        return 'Tx'
    return 'skip'


def numeric(text: str) -> bool:
    return bool(re.match(r'^[−\-–]?\d', text.strip())) and not re.fullmatch(r'\d+[A-Z][A-Za-z0-9+−\-]*', text.strip())


def controlling(text: str) -> Optional[str]:
    return CONTROLLING.get(plain(text).replace(',', ''))


def split_reaction_text(text: str) -> str:
    """'N2+M⇌N+N+M' -> 'N2 + M → N + N + M': a + followed by a letter, digit or parenthesis separates species, other +s are charges"""
    sides = re.split(rf'\s*[{ARROWS}]\s*|\s*->\s*', text.replace(' ', ''))
    # N+2 (N2+ as printed: charge before the subscript) is one species, C++2e− two (a + before a stoichiometric factor separates)
    return ' → '.join(' + '.join(re.split(r'(?<=[A-Za-z0-9)+−-])\+(?=[A-Za-z(]|\d+[A-Za-z])', side)) for side in sides)


def has_arrow(text: str) -> bool:
    return any(arrow in text for arrow in ARROWS) or '->' in text


LABEL = re.compile(r'^\(?([A-Z]?\d+[A-Za-z]?)[.)]?$')


def reaction_part(words: list[Word]) -> tuple[str, str, list[Word]]:
    """(label, reaction as 'A + B → C', remaining words with the values) of a row with a reaction arrow"""
    words = sorted(words, key=lambda w: w.x0)
    label = ''
    first = words[0].text
    glued = re.match(r'^\(?([A-Z]?\d+[A-Za-z]?)[.)]\s*(?=[A-Z(])', first)  # '1)N2+M→N+N+M' (label glued to the reaction)
    labelled = LABEL.match(first)
    if labelled and len(words) > 1:
        label, words = labelled.group(1), words[1:]
    elif glued:
        label = glued.group(1)
        words = [Word(first[glued.end() :], words[0].x0, words[0].x1, words[0].top, words[0].bottom), *words[1:]]
    whole = next((i for i, word in enumerate(words) if re.search(rf'\S\s*[{ARROWS}]\s*\S', word.text)), None)
    if whole is not None:  # the reaction in one word (a cell of a scanned table, or set without spaces): the words after it are values
        return label, split_reaction_text(words[whole].text), words[whole + 1 :]
    reaction: list[Word] = []
    for index, word in enumerate(words):
        if numeric(word.text) and any(has_arrow(w.text) for w in reaction) and reaction[-1].text not in ('+', '→', '⇌', '↔'):
            return label, split_reaction_text(''.join(w.text for w in reaction)), words[index:]
        reaction.append(word)
    return label, split_reaction_text(''.join(w.text for w in reaction)), []


def coefficient(text: str) -> float:
    """C as printed: 3.0^22, 7.00×10^21, 6.170·10^−9, 1.38e+22, 2.5^14"""
    value = text.replace('·', '×').replace(' ', '')
    value = re.sub(r'×10\^?', 'x10^', value)
    value = re.sub(r'^(\d+\.\d+)([+-]\d+)$', r'\1e\2', value)  # 4.40+16: e-notation printed without the e (Johnston 2014, row 6)
    try:
        return parse_number(value)
    except ValueError as e:
        raise RateError(f'C {text!r} not understood') from e


def plain_number(text: str) -> float:
    """n or T_d as printed: −1.60, 113,200, 6.328e+4, -113200"""
    value = text.replace('−', '-').replace('–', '-').replace(',', '').replace(' ', '')
    try:
        return parse_number(value)
    except ValueError as e:
        raise RateError(f'{text!r} is no number') from e


def third_bodies(text: str) -> str:
    """'N, C, O' / 'Others' / 'All' / 'M = e−' / 'EnhancedrateforM=N,C,H' -> rate-table third bodies"""
    value = text.split('=', 1)[1] if '=' in text else text
    value = value.strip()
    if value.lower() in ('others', 'other', 'all'):
        return value.lower().rstrip('s') + ('s' if value.lower().startswith('other') else '')
    return ', '.join(printed_species(part) for part in re.split(r'\s*,\s*', value) if part)


def convert_columns(lines: list[list[Word]], overrides: Optional[dict[str, str]] = None) -> Result:
    """A reaction table with columns: from the header line (the first line with a 'Reaction' header and at least two value headers)"""
    header_index = next((i for i, line in enumerate(lines) if sum(header_role(w.text) != 'skip' for w in line) >= 3 and not any(has_arrow(w.text) for w in line)), None)
    if header_index is None:
        raise RateError('no header line with the columns of the table (Reaction, C or A, n, ...)')
    header_line = sorted(lines[header_index], key=lambda w: w.x0)
    starts = [w.x0 for w in header_line if header_role(w.text) == 'reaction'] or [header_line[0].x0]
    bounds = [(start - 6.0, next_start - 6.0) for start, next_start in zip(starts, [*starts[1:], 1e9], strict=True)]
    bounds[0] = (-1e9, bounds[0][1])  # row labels may stand left of the first header
    height = sorted(w.bottom - w.top for w in header_line)[len(header_line) // 2]
    result = Result(header=[])
    state: Optional[tuple[str, str, dict]] = None
    for low, high in bounds:  # two halves side by side (Park 2001): the left one first
        inside = [[w for w in line if low <= (w.x0 + w.x1) / 2 < high] for line in lines[header_index + 1 :]]
        columns = columns_from_header([w for w in header_line if low <= (w.x0 + w.x1) / 2 < high], 0.6 * height)
        for key, role in (overrides or {}).items():
            for column in columns:
                if plain(column.header) == plain(key):
                    column.role = role
        if not result.header:
            result.header = ['label', 'reaction', *[column.header for column in columns if column.role not in ('reaction', 'label')]]
        state = convert_half(inside, columns, result, state)
    return result


def convert_half(lines: list[list[Word]], columns: list[Column], result: Result, state: Optional[tuple[str, str, dict]] = None) -> tuple[str, str, dict]:
    """One half of the table; the reaction of the previous half continues (its third-body rows may go on at the top of this one)"""
    values = [column for column in columns if column.role not in ('reaction', 'label')]
    start = min((column.x0 for column in values if column.role in ('M', 'C', 'n', 'Td', 'Tx', 'formula')), default=0.0)  # where the values begin
    label, reaction, first = state or ('', '', {})
    rows: list[tuple[str, str, dict[str, str], str]] = []  # label, reaction, cells by role, third-body text
    for line in lines:
        if not line:
            continue
        if sum(header_role(w.text) != 'skip' for w in line) >= 3 and not any(has_arrow(w.text) for w in line) and not any(numeric(w.text) for w in line):
            height = sorted(w.bottom - w.top for w in line)[len(line) // 2]
            columns = columns_from_header(line, 0.6 * height)  # the header of a following table on the same page (Johnston Table 5)
            values = [column for column in columns if column.role not in ('reaction', 'label')]
            start = min((column.x0 for column in values if column.role in ('M', 'C', 'n', 'Td', 'Tx', 'formula')), default=0.0)
            label, reaction, first = '', '', {}
            continue
        if any(has_arrow(w.text) for w in line):
            label, reaction, rest = reaction_part(line)
            first = {}
            if not rest:  # a reaction heading without values (Park 2001: the values follow per third body)
                continue
            line = rest
        elif not reaction or not any(numeric(w.text) for w in line):
            continue  # a section heading, a note, or text before the first reaction
        line = signed(line)
        text = ' '.join(w.text for w in line if not numeric(w.text) and (w.x0 + w.x1) / 2 < start - 4)
        cells = assign([w for w in line if (w.x0 + w.x1) / 2 >= start - 4], values)
        by_role = {values[index].role: cell for index, cell in cells.items()}
        for role in ('n', 'Td', 'Tx'):
            by_role.setdefault(role, first.get(role, ''))
        if not first:
            first = dict(by_role)
        rows.append((label, reaction, by_role, by_role.get('M', text)))
        result.raw.append([label, reaction, *[cells.get(index, '') for index in range(len(values))]])
    label_last, reaction_last, first_last = label, reaction, first
    per_reaction: dict[str, int] = {}
    for label, reaction, _, body in rows:
        per_reaction[label + reaction] = per_reaction.get(label + reaction, 0) + bool(body)
    for label, reaction, by_role, body in rows:
        checks = (('reaction', reaction), ('third body', body), ('C', by_role.get('C', '')), ('Tx', by_role.get('Tx', '')))
        uncertain = [f'{name} {value.rstrip("?")}' for name, value in checks if value.endswith('?')]
        key = label + reaction  # as counted above, with the marks
        reaction, body = reaction.rstrip('?'), body.rstrip('?')
        by_role = {role: value.rstrip('?') for role, value in by_role.items()}
        try:
            text, kind, note = convert_reaction(reaction)
            if uncertain:
                note = (note + '; ' if note else '') + 'OCR uncertain, check against the page: ' + ', '.join(uncertain)
            generic = kind in ('molecules', 'atoms')
            bodies_text = third_bodies(body) if body else ''
            if ' + M ' in f' {text} ' or text.startswith('M + ') or ' M ->' in text:
                kind = bodies_text or ('others' if per_reaction[key] else 'all')
                note = note if note and 'not balanced' in note else None  # M is a third body here, not the class 'molecules'
            elif generic:
                kind = bodies_text or kind
            Tx = controlling(by_role.get('Tx', '')) or 'T'
            if by_role.get('formula'):
                C, n, Td = parse_rate(by_role['formula'])
            else:
                C = coefficient(by_role.get('C', ''))
                n = plain_number(by_role.get('n') or '0')
                Td = plain_number(by_role.get('Td') or '0')
        except (RateError, ValueError) as e:
            result.problems.append(f'{label or reaction}: {e}')
            continue
        result.converted.append(Converted(label, text, kind, C, n, Td, note, Tx))
    return label_last, reaction_last, first_last


def signed(line: list[Word]) -> list[Word]:
    """A minus sign read as a word of its own (OCR: '—' or '~' before '1.60') joined to the number after it"""
    result: list[Word] = []
    for word in sorted(line, key=lambda w: w.x0):
        if result and result[-1].text in ('−', '—', '–', '~', '-') and numeric(word.text):
            word = Word('−' + word.text, result[-1].x0, word.x1, word.top, word.bottom)
            result.pop()
        result.append(word)
    return result


def columns_from_header(line: list[Word], gap: float) -> list[Column]:
    """Column headers: words closer than 'gap' belong to one header ('Third body, M')"""
    columns: list[Column] = []
    for word in sorted(line, key=lambda w: w.x0):
        if columns and (word.x0 - columns[-1].x1 < gap or word.text.startswith(('[', '('))):  # a unit belongs to its header
            columns[-1].header += ' ' + word.text
            columns[-1].x1 = word.x1
        else:
            columns.append(Column(word.text, word.x0, word.x1))
    for column in columns:
        column.role = header_role(column.header)
    return columns


def assign(words: list[Word], columns: list[Column]) -> dict[int, str]:
    """Value words to the column under whose header they sit (else the nearest one); words of one column joined"""
    cells: dict[int, str] = {}
    for word in sorted(words, key=lambda w: w.x0):
        centre = (word.x0 + word.x1) / 2
        inside = [i for i, column in enumerate(columns) if column.x0 - 4 <= centre <= column.x1 + 4]
        index = inside[0] if inside else min(range(len(columns)), key=lambda i: abs(columns[i].centre - centre))
        cells[index] = (cells.get(index, '') + ' ' + word.text).strip()
    return cells


# ----------------------------------------------------------------------------------------------------------------------------------
# From the PDF: the lines of a reaction table (one or more tables, continued on following pages)
# ----------------------------------------------------------------------------------------------------------------------------------
def table_lines(path: str, pages: list[int], numbers: list[str], use_ocr: bool = False, glyphs: Optional[dict[str, str]] = None) -> tuple[list[list[Word]], str, list[int]]:
    """Lines of the tables <numbers> (e.g. ['4', '5']), read character by character (text layer) or by OCR: on the first page from the
    caption of the first table on, on later pages from the top; up to the caption of a table not asked for. Returns the lines, the
    caption text and the pages used."""
    from piclas_db.extract.table import ExtractError, char_words, find_captions, lines_of, require_pdfplumber  # noqa: PLC0415

    pdfplumber = require_pdfplumber()
    lines: list[list[Word]] = []
    caption_text, used = '', []
    with pdfplumber.open(path) as pdf:
        for page_number in pages:
            if not 1 <= page_number <= len(pdf.pages):
                raise ExtractError(f'page {page_number} does not exist ({len(pdf.pages)} pages)')
            page = pdf.pages[page_number - 1]
            words = ocr_words_with_exponents(page) if use_ocr or not page.chars else char_words(page, glyphs)
            page_lines = lines_of(words)
            start = 0
            if not caption_text:
                found = find_captions(words, numbers[0])
                if not found:
                    continue
                caption, caption_text = found[0]
                start = next(i for i, line in enumerate(page_lines) if caption in line) + 1
            for line in page_lines[start:]:
                other = [w for w in line if re.match(r'^(TABLE|Table|Tabelle)$', w.text)]
                if other and not any(re.match(rf'^{re.escape(n)}[.:]?$', w.text) for n in numbers for w in line):
                    break  # the caption of another table
                lines.append(line)
            used.append(page_number)
    if not caption_text:
        raise ExtractError(f'table {numbers[0]} not found on page(s) {", ".join(str(p) for p in pages)}')
    return lines, caption_text, used


# ----------------------------------------------------------------------------------------------------------------------------------
# Scanned tables (OCR): numbers repaired where this is unambiguous, exponents re-read from the enlarged image
# ----------------------------------------------------------------------------------------------------------------------------------
OCR_ARROW = re.compile(r'[—–\-]+[~>]+|[—–\-]*~+|=>')


def ocr_words_with_exponents(page: Any) -> list[Word]:
    """Words of a scanned page by OCR; a number with a printed superscript exponent (3.0²², read as '3.077' or '3.0%') gets its
    exponent from a second reading of the region above the line, enlarged and limited to digits (3.0^22); where that reading is not
    two clean digits the word is marked with '?' for the user"""
    import shutil  # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    from piclas_db.extract.table import ExtractError  # noqa: PLC0415

    if shutil.which('tesseract') is None:
        raise ExtractError('the page has no text layer and Tesseract is not installed for OCR')
    resolution = 600
    scale = resolution / 72
    image = page.to_image(resolution=resolution).original.convert('L')
    with tempfile.NamedTemporaryFile(suffix='.png') as file:
        image.save(file.name)
        tsv = subprocess.run(['tesseract', file.name, '-', '--psm', '6', 'tsv'], capture_output=True, text=True, check=False).stdout
    words: list[Word] = []
    for line in tsv.splitlines()[1:]:
        fields = line.split('\t')
        if len(fields) != 12 or not fields[11].strip() or float(fields[10]) <= 0:
            continue
        left, top, width, height = (int(fields[i]) for i in (6, 7, 8, 9))
        text = ocr_cleaned(fields[11].strip())
        mantissa = re.match(r'^(\d\.\d{1,2})(\S{1,3})$', text)
        if mantissa and not re.fullmatch(r'\d\.\d+', text):
            exponent = reread(image, (left + int(width * 0.55), top - int(height * 0.2), left + width + int(height * 0.15), top + int(height * 0.6)))
            text = f'{mantissa.group(1)}^{exponent}' if exponent else f'{mantissa.group(1)}^?'
        words.append(Word(text, left / scale, (left + width) / scale, top / scale, (top + height) / scale))
    return words


def reread(image: Any, box: tuple[int, int, int, int]) -> Optional[str]:
    """Digits in a small region (an exponent), read enlarged 4x; None unless it is one or two digits"""
    import subprocess  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    crop = image.crop(box)
    crop = crop.resize((crop.width * 4, crop.height * 4))
    with tempfile.NamedTemporaryFile(suffix='.png') as file:
        crop.save(file.name)
        digits = subprocess.run(['tesseract', file.name, '-', '--psm', '7', '-c', 'tessedit_char_whitelist=0123456789'], capture_output=True, text=True, check=False).stdout.strip()
    return digits if re.fullmatch(r'\d{1,2}', digits) else None


def ocr_cleaned(text: str) -> str:
    """Unambiguous repairs of OCR words: arrows (—~, ->), a decimal comma (1,60 but not 113,200), a minus read as a dash or tilde"""
    text = OCR_ARROW.sub('→', text)
    if re.fullmatch(r'[—–~-]?\d,\d{1,2}', text):
        text = text.replace(',', '.')
    return re.sub(r'^[—–~]', '−', text)


# ----------------------------------------------------------------------------------------------------------------------------------
# Scanned tables cell by cell (Park 1993, 1994): column boundaries from the header, every cell read on its own with the characters
# its column can hold, exponents of C read again from their own enlarged crop
# ----------------------------------------------------------------------------------------------------------------------------------
WHITELIST = {
    'reaction': 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-=>(),;*',
    'M': 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-,;*%~',
    'Tx': 'TaevrxtV',
    'C': '0123456789.',
    'n': '0123456789.-',
    'Td': '0123456789,',
}
CANONICAL = {'reaction': 'Reaction', 'M': 'M', 'Tx': 'Tf', 'C': 'C', 'n': 'n', 'Td': 'Df', 'label': 'Nr', 'formula': 'Rate', 'skip': 'Source'}


def ocr_cell(image: Any, box: tuple[int, int, int, int], role: str, scale: int = 1) -> str:
    """Text of one cell, read as one line with the characters its column can hold"""
    import subprocess  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    crop = image.crop(box)
    if scale > 1:
        crop = crop.resize((crop.width * scale, crop.height * scale))
    with tempfile.NamedTemporaryFile(suffix='.png') as file:
        crop.save(file.name)
        command = ['tesseract', file.name, '-', '--psm', '7', '-c', f'tessedit_char_whitelist={WHITELIST.get(role, "")}'] if role in WHITELIST else ['tesseract', file.name, '-', '--psm', '7']
        return subprocess.run(command, capture_output=True, text=True, check=False).stdout.strip()


def scan_coefficient(image: Any, box: tuple[int, int, int, int]) -> str:
    """C of a scanned cell: mantissa with one decimal (3.0) and an exponent set as superscript (22); the exponent read from the cell and
    again from its own enlarged crop; '3.0^22' if both agree, '3.0^22?' if not (the user checks)"""
    whole = ocr_cell(image, box, 'C')
    match = re.fullmatch(r'(\d\.\d)(\d{1,2})', whole)
    left, top, right, bottom = box
    split = left + int(0.55 * (right - left))
    again = ocr_cell(image, (split, top, right, top + int(0.6 * (bottom - top))), 'C', scale=3)
    leading = re.match(r'\d\.\d', whole)
    mantissa = match.group(1) if match else (leading.group(0) if leading else whole)
    exponent = match.group(2) if match else ''
    if exponent and again == exponent:
        return f'{mantissa}^{exponent}'
    candidate = exponent or (again if re.fullmatch(r'\d{1,2}', again) else '')
    return f'{mantissa}^{candidate}?' if candidate else f'{whole}?'


def scan_species(text: str) -> str:
    """Species of a scanned cell with the usual OCR errors of subscripts and charges translated, marked with '?' for the user: a comma
    or semicolon after a letter is the subscript 2 (N, -> N2), '*' or 't' after a species the charge (O* -> O+), '~' after e the
    minus (e~ -> e-), '%' or a stacked '2+' read as one character stays unknown (N% -> N?)"""
    value = text.strip()
    original = value
    value = re.sub(r'(?<=[A-Z])[,;](?=[+*]|$)', '2', value)
    value = re.sub(r'(?<=[A-Za-z0-9])[*t](?=$)', '+', value) if value != 't' else value
    value = re.sub(r'^e[~\-]?$', 'e-', value)
    if re.search(r'[%~;,*]', value) or not re.fullmatch(r'[A-Z][A-Za-z0-9]*\+*|e-', value):
        return f'{value}?'
    return value if value == original else f'{value}?'


def scan_reaction(text: str) -> str:
    """A scanned reaction with OCR repairs: the arrow (—>, ->, >), commas for the subscript 2 (N,+M -> N2+M), a 4 between two + (the
    + read twice: N+N4+M -> N+N+M); marked with '?' where something was changed"""
    value = OCR_ARROW.sub('→', text.replace('->', '→'))
    value = re.sub(r'(?<=[A-Za-z0-9])>(?=[A-Z])', '→', value)
    repaired = re.sub(r'(?<=[A-Z])[,;](?=[+→])', '2', value)
    repaired = re.sub(r'(?<=[A-Z])4\+', '+', repaired)
    return repaired if repaired == value else repaired + '?'


def scan_table_lines(page: Any, numbers: list[str], roles: list[str]) -> tuple[list[list[Word]], str]:
    """Lines of a scanned reaction table, read cell by cell: the header line (column positions) and the rows below it, each cell as
    one word at its column's centre; 'roles' gives the role of each header column from left to right (reaction, M, Tx, C, n, Td, skip)"""
    from piclas_db.extract.table import ExtractError, find_captions, lines_of  # noqa: PLC0415

    resolution = 600
    scale = resolution / 72
    image = page.to_image(resolution=resolution).original.convert('L')
    words = ocr_words_with_exponents(page)
    page_lines = lines_of(words)
    found = find_captions(words, numbers[0])
    caption_text = found[0][1] if found else ''
    start = next((i for i, line in enumerate(page_lines) if found and found[0][0] in line), -1) + 1
    header_index = next((i for i in range(start, min(start + 4, len(page_lines))) if len(page_lines[i]) >= len(roles) - 1), None)
    if header_index is None:
        raise ExtractError(f'no header line below the caption of table {numbers[0]}')
    header = sorted(page_lines[header_index], key=lambda w: w.x0)
    height = sorted(w.bottom - w.top for w in header)[len(header) // 2]
    columns = columns_from_header(header, 0.6 * height)
    if len(columns) != len(roles):
        raise ExtractError(f'{len(columns)} header columns ({", ".join(c.header for c in columns)}) but {len(roles)} roles given (--columns)')
    for column, role in zip(columns, roles, strict=True):
        column.role = role
    centres = [column.centre for column in columns]
    bounds = []
    for index, column in enumerate(columns):
        low = -1e9 if index == 0 else bounds[-1][1]
        if index + 1 == len(columns):
            high = 1e9
        elif column.role == 'reaction' and index + 2 < len(columns):  # reactions are long, the next column's values short
            high = centres[index + 1] - (centres[index + 2] - centres[index + 1]) / 2
        else:
            high = (centres[index] + centres[index + 1]) / 2
        bounds.append((low, high))
    lines = [[Word(CANONICAL[column.role], column.x0, column.x1, header[0].top, header[0].bottom) for column in columns]]
    for line in page_lines[header_index + 1 :]:
        if any(re.match(r'^(TABLE|Table)$', w.text) for w in line):
            break  # the next table
        top, bottom = min(w.top for w in line), max(w.bottom for w in line)
        pad = 0.35 * (bottom - top)
        cells = []
        for column, (low, high) in zip(columns, bounds, strict=True):
            if column.role == 'skip' or not any(low <= (w.x0 + w.x1) / 2 < high for w in line):
                continue
            box = (int(max(low, 0) * scale), int((top - pad) * scale), int(min(high, float(page.width)) * scale), int((bottom + pad) * scale))
            text = scan_coefficient(image, box) if column.role == 'C' else ocr_cell(image, box, column.role)
            if column.role == 'reaction':
                text = scan_reaction(text)
            elif column.role == 'M' and text:
                text = scan_species(text)
            elif column.role == 'Tx' and text == 'T':
                text = 'T?'  # the subscript (Ta, Tv) is easily lost in a scan
            if column.role == 'n' and re.fullmatch(r'-?\d\d\d', text):
                text = f'{text[:-2]}.{text[-2:]}'  # the decimal point lost: -160 -> -1.60
            if text:
                cells.append(Word(text, column.centre - 1, column.centre + 1, top, bottom))
        if cells:
            lines.append(cells)
    return lines, caption_text
