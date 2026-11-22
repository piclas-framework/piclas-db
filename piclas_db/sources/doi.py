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
import pathlib
import re
import shutil
import subprocess
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
TITLE_MATCH = 0.6  # share of the title's words that must appear in the first pages


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


def ascii_fold(text: str) -> str:
    """Gökçen -> Gokcen, Müller -> Muller (letters without accents)"""
    import unicodedata  # noqa: PLC0415

    return unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')


def record_year(record: dict) -> Optional[int]:
    for key in ('issued', 'published-print', 'published-online', 'created'):
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


def plumber_text(path: pathlib.Path, pages: int) -> Optional[str]:
    """Text by pdfplumber; None if it is not installed or cannot read the file"""
    try:
        import pdfplumber  # noqa: PLC0415

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


def get_json(url: str, timeout: float) -> Optional[dict]:
    """JSON of a Crossref URL; None for 'not found' (HTTP 404), Unreachable for network errors"""
    headers = {'User-Agent': f'piclas-db/{Common().version} (https://github.com/piclas-framework/piclas-db)', 'Accept': 'application/json'}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as response:  # noqa: S310 (fixed https host)
            return json.loads(response.read().decode('utf-8')).get('message')
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise Unreachable(f'Crossref: HTTP {e.code}') from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise Unreachable(f'Crossref not reachable: {e}') from e
    except ValueError:
        return None


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
    title = ' '.join(str((record.get('title') or [''])[0]).split())
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
    message = get_json('https://api.crossref.org/works?' + urllib.parse.urlencode({'query.bibliographic': query[:300], 'rows': 3}), timeout) or {}
    return list(message.get('items') or [])


def record_title(record: dict) -> str:
    return ' '.join(str((record.get('title') or [''])[0]).split())


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


def checked(path: pathlib.Path, text: str, found: list[tuple[str, str]], result: Citation) -> Citation:
    """DOI candidates checked at Crossref (title on the first pages), else a Crossref search for the first lines"""
    has_text = bool(text.strip())
    haystack = text if has_text else re.sub(r'[_\-]+', ' ', path.stem)
    rejected = []
    for candidate, where in found[:5]:
        record = crossref(candidate)
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
        for record in search(' '.join(lines)):
            title = record_title(record)
            if title and title_found(title, haystack) >= TITLE_MATCH and record.get('DOI'):
                result.doi, result.doi_found_in, result.title = str(record['DOI']), 'Crossref search', title
                result.first_author, result.year = record_author(record), record_year(record)
                result.notes.append('DOI found by searching Crossref for the first lines of the PDF: check it at the link')
                if not result.reference:
                    result.reference, result.reference_from = format_citation(record), 'crossref'
                break
    if rejected:
        result.notes.append('not taken: ' + '; '.join(rejected))
    return result
