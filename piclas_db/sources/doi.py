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
"""DOI and citation of a paper (PDF) for `import --literature`, so that --doi and --reference need not be typed

The DOI is searched, in this order, in the PDF metadata (document info and XMP), in the text of the first two pages (where journals
print the article's own DOI; reference lists come later) and in the file name (IOP `0953-4075_2F21_2F6_2F014`, APS
`PhysRevA_6_1507`, URL-encoded DOIs). The citation is looked up at Crossref (api.crossref.org); its title is then searched in the
first pages, which catches a download that contains another article than the DOI says. The user checks the result at
https://doi.org/<DOI>, printed by the import.
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import json
import logging
import os
import pathlib
import re
import shutil
import subprocess
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass, field
from typing import Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.common.common_vars import Common
# ==================================================================================================================================

DOI_PATTERN = re.compile(r'\b(10\.\d{4,9}/[^\s"<>{}\[\]]+)', re.IGNORECASE)
CROSSREF = 'https://api.crossref.org/works/'
TITLE_MATCH = 0.6  # share of the title's words that must appear in the first pages (DOI found in the PDF or its name)
BYLINE = re.compile(r'^by\b|\b[A-Z]\.|@|\b(?:abstract|university|universit\w*|institut\w*|department|laborator\w*)\b', re.IGNORECASE)
SUFFIXES = {'jr', 'sr', 'ii', 'iii', 'iv'}


@dataclass
class Citation:
    doi: Optional[str] = None
    doi_found_in: Optional[str] = None  # metadata, first pages, file name, given
    reference: Optional[str] = None
    reference_from: Optional[str] = None  # crossref, given
    title: Optional[str] = None
    first_author: Optional[str] = None  # family name of the first author (Crossref)
    year: Optional[int] = None
    notes: list[str] = field(default_factory=list)  # warnings for the user

    def key(self, taken: set[str]) -> Optional[str]:
        """Literature key 'author-year' (ASCII, lower case), with b, c, ... if taken; None without author or year"""
        if not (self.first_author and self.year):
            return None
        base = re.sub(r'[^a-z0-9]+', '-', ascii_fold(self.first_author).lower()).strip('-') + f'-{self.year}'
        for suffix in ['', *'bcdefghijklmnopqrstuvwxyz']:
            if base + suffix not in taken:
                return base + suffix
        return None

    @property
    def link(self) -> Optional[str]:
        return f'https://doi.org/{self.doi}' if self.doi else None


UMLAUTS = {'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'Ä': 'Ae', 'Ö': 'Oe', 'Ü': 'Ue', 'ß': 'ss', 'ẞ': 'SS'}


def ascii_fold(text: str) -> str:
    """Letters without accents, umlauts spelled out: Müller -> Mueller, MÜLLER -> MUELLER, Gökçen -> Goekcen, Gonçalves -> Goncalves.
    The text is NFC-normalized first, so a decomposed ü (u + combining diaeresis) is spelled out too."""

    def spell(match: re.Match[str]) -> str:
        word = match.group(0)
        spelled = ''.join(UMLAUTS.get(char, char) for char in word)
        return spelled.upper() if word.isupper() else spelled

    composed = re.sub(r'\w+', spell, unicodedata.normalize('NFC', text))
    return unicodedata.normalize('NFKD', composed).encode('ascii', 'ignore').decode('ascii')


def ascii_words(text: str) -> list[str]:
    """Words with umlauts spelled out (Müller -> Mueller)"""
    return re.findall(r'[A-Za-z0-9]+', ascii_fold(text))


def plain_words(text: str) -> list[str]:
    """Words with all accents dropped (Müller -> Muller)"""
    return re.findall(r'[A-Za-z0-9]+', unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii'))


def author_found(record: dict, text: str) -> bool:
    """The first author's family name (all its parts of 2+ letters) in the text, in both spellings (Mueller and Muller for Müller);
    letter runs, because affiliation markers stick to names in extracted text (R.K. Janev1,2)"""
    authors = record.get('author') or []
    family = str(authors[0].get('family') or authors[0].get('name') or '') if authors else ''
    haystack = {word.lower() for word in re.findall(r'[A-Za-z]+', ' '.join(ascii_words(text) + plain_words(text)))}
    spellings = [[word.lower() for word in words(family) if len(word) > 1] for words in (ascii_words, plain_words)]
    return any(names and all(name in haystack for name in names) for names in spellings)


def edits(pattern: str, text: str) -> int:
    """Fewest edits (insert, delete or replace a character) that turn pattern into some part of text: approximate substring matching
    with Myers' bit-parallel algorithm (1999), fast also for two pages of text. The search variant: a match may start anywhere."""
    m = len(pattern)
    if not m:
        return 0
    mask, high = (1 << m) - 1, 1 << (m - 1)
    peq: dict[str, int] = {}
    for i, char in enumerate(pattern):
        peq[char] = peq.get(char, 0) | (1 << i)
    pv, mv, score, best = mask, 0, m, m
    for char in text:
        eq = peq.get(char, 0)
        xv = eq | mv
        xh = (((eq & pv) + pv) ^ pv) | eq
        ph = (mv | ~(xh | pv)) & mask
        mh = pv & xh
        if ph & high:
            score += 1
        elif mh & high:
            score -= 1
        ph = (ph << 1) & mask
        mh = (mh << 1) & mask
        pv = (mh | ~(xv | ph)) & mask
        mv = ph & xv
        best = min(best, score)
    return best


def squeeze(text: str) -> str:
    """Letters and digits only, lower case, accents dropped"""
    return ''.join(plain_words(text)).lower()


def title_errors(title: str, text: str) -> int:
    """Characters of the title (letters and digits) that differ from the closest part of the text, in order"""
    squeezed, haystack = squeeze(title), squeeze(text)
    return 0 if squeezed in haystack else edits(squeezed, haystack)


def title_share(title: str, text: str) -> int:
    """Percentage (rounded down) of the title's letters and digits found in the text, in order (for messages)"""
    squeezed = squeeze(title)
    return int(100 * max(0, len(squeezed) - title_errors(title, text)) / len(squeezed)) if squeezed else 0


def title_in_text(title: str, text: str) -> bool:
    """The whole title is in the text, in order: compared by letters and digits only, so line breaks, hyphenation, punctuation,
    accents and formula spacing (H 2, H2) do not matter; up to 5 % of the characters may differ (OCR of old scans: 'Ar+' read as
    'AI+', Man et al. 1987), none in titles under 20 characters (a short title matches too easily: 'Collision Processes of H+')"""
    squeezed = squeeze(title)
    return bool(squeezed) and title_errors(title, text) <= len(squeezed) // 20


def title_lines(text: str) -> str:
    """The title from the start of the first page: lines up to the byline (by, initials R.K., e-mail, Abstract, affiliation), at most 4"""
    lines: list[str] = []
    for line in (line.strip() for line in text.splitlines()):
        if not line:
            continue
        if BYLINE.search(line) or len(lines) == 4:
            break
        lines.append(line)
    return ' '.join(lines)


def from_openalex(work: dict) -> Optional[dict]:
    """OpenAlex work as a Crossref-like record (title, first author's family name, year, DOI or None); None without title"""
    title = str(work.get('display_name') or work.get('title') or '')
    if not title:
        return None
    record: dict = {'title': [title], 'DOI': clean(str(work['doi'])) if work.get('doi') else None}
    if work.get('publication_year'):
        record['issued'] = {'date-parts': [[int(work['publication_year'])]]}
    authors = work.get('authorships') or []
    name = str(((authors[0].get('author') or {}).get('display_name') or authors[0].get('raw_author_name') or '') if authors else '')
    if ',' in name:  # Janev, R. K.
        family = name.partition(',')[0].strip()
    else:  # R. K. Janev (compound names lose their particles: Hans von der Heydt -> Heydt)
        words = [word for word in name.split() if word.rstrip('.').lower() not in SUFFIXES]
        family = words[-1] if words else ''
    if family:
        record['author'] = [{'family': family}]
    return record


def openalex_search(text: str, timeout: float = 15.0) -> tuple[list[dict], str]:
    """(records of the OpenAlex works best matching the title of the PDF, error); one request per file. OpenAlex also knows reports,
    theses and books without DOI. Queried with the title lines only (it needs all query words, author initials would prevent hits).
    Without a key all requests of one IP share a small daily budget: $OPENALEX_API_KEY (free, openalex.org/settings/api) raises it."""
    query = ' '.join(re.sub(r'[^\w\s]|\d', ' ', title_lines(text)).split())[:200]
    if not query:
        return [], ''
    params: dict[str, object] = {'search': query, 'per-page': 5, 'select': 'doi,display_name,publication_year,authorships'}
    from piclas_db import config  # noqa: PLC0415

    found = config.identity()
    if found:
        params['mailto'] = found[1]
    if os.environ.get('OPENALEX_API_KEY'):
        params['api_key'] = os.environ['OPENALEX_API_KEY']
    try:
        data = fetch_json('https://api.openalex.org/works?' + urllib.parse.urlencode(params), timeout, 'OpenAlex')
    except Unreachable as e:  # only a fallback: the error is reported, the run is not offline
        return [], str(e)
    return [record for record in map(from_openalex, (data or {}).get('results') or []) if record], ''


def record_year(record: dict) -> Optional[int]:
    for key in ('published-print', 'issued', 'published-online', 'created'):  # the printed issue first: 'issued' is the earliest date (often online-first)
        parts = (record.get(key) or {}).get('date-parts') or [[None]]
        if parts and parts[0] and parts[0][0]:
            return int(parts[0][0])
    return None


def record_author(record: dict) -> Optional[str]:
    authors = record.get('author') or []
    return str(authors[0].get('family') or authors[0].get('name') or '') or None if authors else None


def clean(doi: str) -> str:
    """DOI without trailing punctuation or a URL prefix; lower case is not applied (DOIs are case-insensitive but printed as given)"""
    doi = re.sub(r'^(?:https?://)?(?:dx\.)?doi\.org/', '', doi.strip(), flags=re.IGNORECASE)
    doi = doi.rstrip('.,;:)]}\'"')
    return doi.removesuffix('.pdf')


def from_file_name(name: str) -> list[str]:
    """DOIs a downloaded file's name may encode (several where the publisher is ambiguous, e.g. AIP and AIAA both use '1_<n>')"""
    stem = pathlib.Path(name).stem
    patterns = (
        (r'(\d{4}-\d{3}[\dXx])_2F(\d+)_2F(\d+)_2F(\d+)', ['10.1088/{0}/{1}/{2}/{3}']),  # IOP
        (r'(PhysRev[A-Z]?|RevModPhys)_(\d+)_(\d+)', ['10.1103/{0}.{1}.{2}']),  # APS
        (r'6_(\d{4}-\d+)', ['10.2514/6.{0}']),  # AIAA meeting paper
        (r'1_(\d{4,7})', ['10.2514/1.{0}', '10.1063/1.{0}']),  # AIAA journal or AIP
        (r'([a-z]{3,6})_(\d{4})_(\d{4})', ['10.1006/{0}.{1}.{2}']),  # Academic Press (e.g. adnd_1997_0732)
    )
    for pattern, templates in patterns:
        match = re.fullmatch(pattern, stem)
        if match:
            return [template.format(*match.groups()) for template in templates]
    decoded = urllib.parse.unquote(stem.replace('_2F', '/').replace('_2f', '/'))
    match = DOI_PATTERN.search(decoded)
    return [clean(match.group(1))] if match else []


def quiet_pdfminer() -> None:
    """pdfminer (under pdfplumber) logs a warning for every incomplete font description of older PDFs ("Could not get FontBBox
    from font descriptor ..."); the text is extracted anyway, so only errors are shown"""
    logging.getLogger('pdfminer').setLevel(logging.ERROR)


def plumber_text(path: pathlib.Path, pages: int) -> Optional[str]:
    """Text by pdfplumber; None if it is not installed or cannot read the file"""
    quiet_pdfminer()
    try:
        import pdfplumber  # noqa: PLC0415  # ty: ignore[import-not-found]  # optional, pdftotext otherwise

        with pdfplumber.open(path) as pdf:
            return '\n'.join(page.extract_text() or '' for page in pdf.pages[:pages])
    except ImportError:
        return None
    except Exception:  # noqa: BLE001 (damaged or unusual PDF: fall back to pdftotext)
        return None


def pdf_text(path: pathlib.Path, pages: int = 2) -> str:
    """Text of the first pages: pdfplumber if installed, else pdftotext, else nothing"""
    text = plumber_text(path, pages)
    if text is not None:
        return text
    tool = shutil.which('pdftotext')
    if tool:
        try:
            return subprocess.run([tool, '-l', str(pages), str(path), '-'], capture_output=True, text=True, timeout=60, check=False).stdout  # noqa: S603 (fixed tool)
        except (OSError, subprocess.SubprocessError):
            return ''
    return ''


def pdf_metadata(path: pathlib.Path) -> str:
    """Document info and XMP metadata as text (uncompressed in most PDFs; compressed streams are inflated where possible)"""
    data = path.read_bytes()
    parts = [m.group(0).decode('latin-1') for m in re.finditer(rb'<x:xmpmeta.*?</x:xmpmeta>', data, re.DOTALL)]
    parts += [m.group(0).decode('latin-1') for m in re.finditer(rb'/(?:doi|DOI|Subject|Title|Keywords|Identifier)\s*\((?:[^()\\]|\\.)*\)', data)]
    for stream in re.finditer(rb'stream\r?\n(.*?)\r?\nendstream', data[:2_000_000], re.DOTALL):
        try:
            text = zlib.decompress(stream.group(1))
        except zlib.error:
            continue
        if b'xmpmeta' in text:
            parts.append(text.decode('latin-1'))
    return '\n'.join(parts)


def candidates(path: pathlib.Path, text: str) -> list[tuple[str, str]]:
    """(DOI, where found), best first: metadata, first pages, file name; each DOI once"""
    found: list[tuple[str, str]] = []
    for where, content in (('metadata', pdf_metadata(path)), ('first pages', text)):
        found += [(clean(m.group(1)), where) for m in DOI_PATTERN.finditer(content.replace('\u2010', '-').replace('\u2011', '-'))]
    found += [(doi, 'file name') for doi in from_file_name(path.name)]
    unique: dict[str, tuple[str, str]] = {}
    for doi, where in found:
        unique.setdefault(doi.lower(), (doi, where))
    return list(unique.values())


class Unreachable(Exception):
    """Crossref could not be asked (offline, firewall, timeout)"""


def fetch_json(url: str, timeout: float, service: str = 'Crossref') -> Optional[dict]:
    """Whole JSON answer of a web service; None for 'not found' (HTTP 404), Unreachable (naming the service) for network errors"""
    headers = {'User-Agent': f'piclas-db/{Common().version} (https://github.com/piclas-framework/piclas-db)', 'Accept': 'application/json'}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as response:  # noqa: S310 (fixed https hosts)
            data = json.loads(response.read().decode('utf-8'))
            return data if isinstance(data, dict) else None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise Unreachable(f'{service}: HTTP {e.code}' + (' (too many requests)' if e.code == 429 else '')) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise Unreachable(f'{service} not reachable: {e}') from e
    except ValueError:
        return None


def get_json(url: str, timeout: float) -> Optional[dict]:
    """The 'message' of a Crossref answer; None for 'not found', Unreachable for network errors"""
    data = fetch_json(url, timeout, 'Crossref')
    return data.get('message') if data else None


def crossref(doi: str, timeout: float = 15.0) -> Optional[dict]:
    """Crossref record of a DOI (None if Crossref does not know it; Unreachable if Crossref cannot be asked)"""
    return get_json(CROSSREF + urllib.parse.quote(doi, safe='/'), timeout)


def format_citation(record: dict) -> str:
    """'A. B. Author, C. Other, Title, Journal 8(1):9-23, 1994' from a Crossref record"""
    authors = []
    for person in record.get('author') or []:
        given = ' '.join(f'{part[0]}.' for part in re.split(r'[\s.]+', str(person.get('given', ''))) if part)
        authors.append(' '.join(x for x in (given, str(person.get('family', ''))) if x) or str(person.get('name', '')))
    if len(authors) > 6:
        authors = [*authors[:3], 'et al.']
    title = record_title(record)
    journal = str((record.get('short-container-title') or record.get('container-title') or [''])[0])
    volume, issue, page = record.get('volume'), record.get('issue'), record.get('page') or record.get('article-number')
    where = journal + (f' {volume}' if volume else '') + (f'({issue})' if issue else '') + (f':{page}' if page else '')
    year = record_year(record)
    return ', '.join(part for part in (', '.join(authors), title, where.strip(), str(year) if year else '') if part)


def title_found(title: str, text: str) -> float:
    """Share of the title's words (4 letters or more) that occur in the text"""
    words = [w for w in re.findall(r'[a-z0-9]+', title.lower()) if len(w) >= 4]
    if not words:
        return 1.0
    haystack = set(re.findall(r'[a-z0-9]+', text.lower()))
    return sum(word in haystack for word in words) / len(words)


def search(query: str, timeout: float = 15.0) -> list[dict]:
    """Crossref bibliographic search, best matches first (Unreachable if Crossref cannot be asked)"""
    message = get_json('https://api.crossref.org/works?' + urllib.parse.urlencode({'query.bibliographic': query[:300], 'rows': 5}), timeout) or {}
    return list(message.get('items') or [])


def record_title(record: dict) -> str:
    """Title of a Crossref record as text: markup removed, subscripts of formulas joined (CO<sub>2</sub>, 'CO 2 –N 2' -> CO2–N2)"""
    return tidy_title(str((record.get('title') or [''])[0]))


def tidy_title(title: str) -> str:
    title = ' '.join(re.sub(r'<[^>]+>', '', title).split())
    title = re.sub(r'\b((?:[A-Z][a-z]?)+) (\d{1,2})(?=[\s–\-+,:;)]|$)', r'\1\2', title)  # 'CO 2' -> 'CO2', not 'Part 2' or 'Table 2'
    return re.sub(r'(\w) ([–\-])(?=\w)', r'\1\2', title)  # 'CO2 –N2' -> 'CO2–N2' (dash attached on one side only)


def paper_citation(path: pathlib.Path, doi: Optional[str], reference: Optional[str], lookup: bool = True) -> Citation:
    """DOI and citation of a paper: given values win; the rest is found in the PDF, its name and at Crossref.

    A DOI from the PDF or its name is accepted when Crossref knows it and its title is on the first pages (title not checked for
    scans without text). Without a DOI the PDF's first lines (or the file name) are searched at Crossref. Offline, a DOI from the PDF
    or an unambiguous file name is taken unchecked.
    """
    text = pdf_text(path)
    found = [(clean(doi), 'given')] if doi else candidates(path, text)
    if lookup:
        try:
            return checked(path, text, found, Citation(reference=reference, reference_from='given' if reference else None))
        except Unreachable as e:
            note = str(e)
    else:
        note = 'not checked at Crossref (--no-lookup)'
    result = Citation(reference=reference, reference_from='given' if reference else None, notes=[note])
    unambiguous = [c for c in found if c[1] != 'file name'] or (found if len(found) == 1 else [])
    if unambiguous:
        result.doi, result.doi_found_in = unambiguous[0]
        result.notes.append('check the DOI at the link')
    elif found:
        result.notes.append(f'the file name allows several DOIs ({", ".join(d for d, _ in found)}): give --doi')
    return result


def search_hit(record: dict, text: str, haystack: str) -> bool:
    """A search hit is the paper only if its whole title is in the text, in order, and its first author is there; a scan without
    text has only its file name: 60 % of the title words and the author"""
    title = record_title(record)
    if not title:
        return False
    if text.strip():
        return title_in_text(title, text) and author_found(record, text)
    return title_found(title, haystack) >= TITLE_MATCH and author_found(record, haystack)


def evidence(record: dict, text: str) -> tuple[bool, bool]:
    """How well a search hit fits the first pages beyond title and author: (journal or book title there, year there). Tells the
    journal article from its conference version with the same title and author (Park et al. 2001 and AIAA paper 2000-210)"""
    containers = [str(container) for key in ('container-title', 'short-container-title') for container in record.get(key) or [] if container]  # old pages: J. Phys. B
    year = record_year(record)
    return any(title_in_text(container, text) for container in containers), bool(year) and str(year) in re.findall(r'\d{4}', text)


PAGE_SLACK = 3  # extra pages a download may have (cover, download sheet, blank page)


def page_range(record: dict) -> Optional[int]:
    """Number of pages of a record's page range ('8-689' -> 682); None without a range"""
    match = re.fullmatch(r'\s*(\d+)\s*[-\u2013]\s*(\d+)\s*', str(record.get('page') or ''))
    if not match or int(match.group(2)) < int(match.group(1)):
        return None
    return int(match.group(2)) - int(match.group(1)) + 1


def page_fit(record: dict, pages: Optional[int]) -> int:
    """1 if the PDF has the pages of the record's range (one fewer up to a few more: cover, download sheet), -1 if clearly not (more
    than this chapter or article, or only a part), 0 without a range (books, conference papers) or page count"""
    length = page_range(record)
    if not (length and pages):
        return 0
    return 1 if length - 1 <= pages <= length + PAGE_SLACK else -1


def pdf_pages(path: pathlib.Path) -> Optional[int]:
    """Number of pages of the PDF (pdfinfo, else pdfplumber); None if unknown"""
    tool = shutil.which('pdfinfo')
    if tool:
        try:
            info = subprocess.run([tool, str(path)], capture_output=True, text=True, timeout=60, check=False).stdout  # noqa: S603 (fixed tool)
            match = re.search(r'^Pages:\s+(\d+)', info, re.MULTILINE)
            if match:
                return int(match.group(1))
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        import pdfplumber  # noqa: PLC0415  # ty: ignore[import-not-found]  # optional

        with pdfplumber.open(path) as pdf:
            return len(pdf.pages)
    except Exception:  # noqa: BLE001 (not installed, damaged or unusual PDF)
        return None


def best_hit(hits: list[dict], text: str, scan: bool = False, pages: Optional[int] = None) -> Optional[dict]:
    """Of the fitting search hits: the one whose title differs from the page in the fewest characters (a sibling of a paper series may
    fit within the tolerance), then the one whose page range fits the page count of the PDF (a chapter against its whole book: Huber
    and Herzberg 1979; an article against its conference version), then the one whose journal and year are on the page, then the
    search order (max returns the first of equals); a single hit is taken even without evidence. For scans the file name is compared
    by the word share: no character errors there."""
    if not hits:
        return None
    errors = {id(record): 0 if scan else title_errors(record_title(record), text) for record in hits}
    return max(hits, key=lambda record: (-errors[id(record)], page_fit(record, pages), *evidence(record, text)))


def take(result: Citation, record: dict, doi: Optional[str], where: str) -> None:
    result.doi, result.doi_found_in, result.title = doi, where if doi else None, record_title(record) or None
    result.first_author, result.year = record_author(record), record_year(record)
    if not result.reference:
        result.reference, result.reference_from = format_citation(record), 'openalex' if where == 'OpenAlex' else 'crossref'


def checked(path: pathlib.Path, text: str, found: list[tuple[str, str]], result: Citation) -> Citation:
    """DOI candidates checked at Crossref (title on the first pages), else a Crossref search for the first lines"""
    has_text = bool(text.strip())
    haystack = text if has_text else re.sub(r'[_\-]+', ' ', path.stem)
    rejected = []
    for candidate, where in found[:5]:
        record = crossref(candidate)
        if record is None and where == 'given':  # a DOI given by the user is kept: Crossref does not know every DOI
            result.doi, result.doi_found_in = candidate, where
            result.notes.append(f'{candidate} is not known at Crossref: check the DOI at the link')
            break
        if record is None:
            rejected.append(f'{candidate} ({where}): not at Crossref')
            continue
        title = record_title(record)
        if where != 'given' and has_text and title and title_found(title, text) < TITLE_MATCH:
            rejected.append(f'{candidate} ({where}): "{title}" is not on the first pages')
            continue
        result.doi, result.doi_found_in, result.title = candidate, where, title or None
        result.first_author, result.year = record_author(record), record_year(record)
        if where == 'given' and has_text and title and title_found(title, text) < TITLE_MATCH:
            result.notes.append(f'the title "{title}" is not on the first pages of the PDF: the file may contain another article')
        if not has_text:
            result.notes.append('the PDF has no text layer: title not compared, check the DOI at the link')
        if not result.reference:
            result.reference, result.reference_from = format_citation(record), 'crossref'
        break
    else:
        lines = [line.strip() for line in text.splitlines() if len(line.strip()) > 15][:6] if has_text else [haystack]
        searched = [record for record in search(' '.join(lines)) if record.get('DOI')]
        fitting = [record for record in searched if search_hit(record, text, haystack)]
        hit = best_hit(fitting, haystack, scan=not has_text, pages=pdf_pages(path) if len(fitting) > 1 else None)
        closest_note = None
        if hit is None and searched and has_text:  # the closest rejected hit, for the user: give its DOI with --doi if it is the paper
            closest = max(searched, key=lambda record: title_share(record_title(record), text))
            closest_note = f'Crossref search: {closest["DOI"]} ({title_share(record_title(closest), text)} % of its title on the page) not taken'
        if hit is not None:
            take(result, hit, str(hit['DOI']), 'Crossref search')
            result.notes.append('DOI found by searching Crossref for the first lines of the PDF: check it at the link')
        elif has_text:  # OpenAlex also knows reports, theses and books without DOI
            records, error = openalex_search(text)
            fitting = [record for record in records if search_hit(record, text, haystack)]
            hit = best_hit(fitting, haystack, scan=not has_text, pages=pdf_pages(path) if len(fitting) > 1 else None)
            if hit is not None:
                take(result, hit, hit.get('DOI'), 'OpenAlex')
                result.notes.append('found by searching OpenAlex for the title: check it' + (' at the link' if hit.get('DOI') else ' (no DOI)'))
            elif error:
                rejected.append(error)
        if closest_note and not result.doi and not result.reference:  # nothing found at all: show what came closest
            rejected.append(closest_note)
    if rejected:
        result.notes.append('not taken: ' + '; '.join(rejected))
    return result
