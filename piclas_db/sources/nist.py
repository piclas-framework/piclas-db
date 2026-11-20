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
"""Parser for energy-level exports of the NIST Atomic Spectra Database (https://physics.nist.gov/asd)

The ASD level form exports tables as CSV (values written as Excel formulas, '="93143.7600"'), tab-separated or formatted text
('|' separated, 'ASCII (text)'); all give the same levels. The header contains the columns
'J' and 'Level (<unit>)' with the unit cm-1, eV or Ry. The species is not part of every export, so it is taken from a spectrum
name above the table (e.g. 'Ar II'), from the file name or from the command line.
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import csv
import io
import re
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import numpy as np
# ==================================================================================================================================

LEVEL_COLUMN = re.compile(r'Level\s*\((cm-1|eV|Ry)\)', re.IGNORECASE)
ROMAN = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6, 'VII': 7, 'VIII': 8, 'IX': 9, 'X': 10}
SPECTRUM = re.compile(r'(?<![A-Za-z])([A-Z][a-z]?)[ _-]?(X|IX|VIII|VII|VI|V|IV|III|II|I)(?![A-Za-z])')


@dataclass
class NistLevels:
    unit: str  # 'cm-1', 'eV' or 'Ry'
    species: Optional[str]  # PICLas name, e.g. 'ArIon1'
    levels: np.ndarray = field(default_factory=lambda: np.empty((0, 2)))  # degeneracy 2J+1, energy in the given unit
    skipped: int = 0  # rows without J or energy (e.g. limits, headers repeated in the table)
    limit: Optional[float] = None  # lowest ionization limit ('Limit' row), in the given unit
    estimated: int = 0  # levels with the energy in brackets or parentheses (theoretical or derived values, e.g. '[126211.5]')
    estimated_mask: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=bool))  # per level: energy in brackets
    doubtful: int = 0  # rows with relative ('+x') or doubtful ('?') energies, left out


def is_nist_levels(text: str) -> bool:
    head = text[:5000]
    return LEVEL_COLUMN.search(head) is not None and re.search(r'(^|[|,"\t])\s*"?J"?\s*([|,"\t]|$)', head, re.MULTILINE) is not None


def piclas_species(text: str) -> Optional[str]:
    """PICLas species name from a spectrum name such as 'Ar II' (-> 'ArIon1')"""
    match = SPECTRUM.search(text)
    if not match:
        return None
    element, charge = match.group(1), ROMAN[match.group(2)] - 1
    return element if charge == 0 else f'{element}Ion{charge}'


def clean(value: str) -> str:
    return value.strip().strip('="').strip('"').strip()


def parse_j(value: str) -> Optional[float]:
    value = clean(value)
    if not value or not re.fullmatch(r'\d+(/\d+)?', value):
        return None  # e.g. empty, '?', or several J values
    return float(Fraction(value))


def parse_energy(value: str) -> Optional[float]:
    """Energy of a level; None for empty cells and for values that are not absolute or doubtful: '1234.5+x' (relative to an
    unknown level of another system), '1234.5?' (level may not be real)"""
    value = clean(value)
    if re.search(r'[a-wyzA-Z]|\+\s*[a-z]|\?|\bx\b', value):
        return None
    value = re.sub(r'[\[\]()]', '', value).strip()
    try:
        return float(value)
    except ValueError:
        return None


def parse_nist_levels(text: str, name_hint: str = '') -> NistLevels:
    """Parse a NIST ASD level export; raises ValueError if the columns are not found"""
    lines = [line for line in text.splitlines() if line.strip() and not set(line.strip()) <= set('-|+ ')]
    header_index = next((i for i, line in enumerate(lines) if LEVEL_COLUMN.search(line)), None)
    if header_index is None:
        raise ValueError('no "Level (...)" column found')
    header = lines[header_index]
    delimiter = '|' if '|' in header else ('\t' if '\t' in header else ',')
    rows = list(csv.reader(io.StringIO('\n'.join(lines[header_index:])), delimiter=delimiter))
    columns = [clean(column) for column in rows[0]]
    level_column = next(i for i, column in enumerate(columns) if LEVEL_COLUMN.search(column))
    unit_match = LEVEL_COLUMN.search(columns[level_column])
    assert unit_match is not None
    if 'J' not in columns:
        raise ValueError('no "J" column found')
    j_column = columns.index('J')
    term_column = columns.index('Term') if 'Term' in columns else None
    prefix_column = columns.index('Prefix') if 'Prefix' in columns else None  # CSV: brackets of the level in their own columns

    levels, skipped, limits, estimated, doubtful, mask = [], 0, [], 0, 0, []
    for row in rows[1:]:
        if len(row) <= max(level_column, j_column):
            skipped += 1
            continue
        j, energy = parse_j(row[j_column]), parse_energy(row[level_column])
        if term_column is not None and len(row) > term_column and clean(row[term_column]).lower() == 'limit' and energy is not None:
            limits.append(energy)
        if j is not None and energy is None and re.search(r'\+\s*[a-z]|\?', clean(row[level_column])):
            doubtful += 1
            continue
        if j is None or energy is None:
            skipped += 1
            continue
        prefix = clean(row[prefix_column]) if prefix_column is not None and len(row) > prefix_column else ''
        bracketed = bool(re.search(r'[\[\(]', clean(row[level_column]) + prefix))
        estimated += bracketed
        mask.append(bracketed)
        levels.append((2.0 * j + 1.0, energy))

    # Spectrum name before the table (the table itself names the next ion in its 'Limit' rows), otherwise from the file name
    species = piclas_species('\n'.join(lines[:header_index])) or piclas_species(name_hint)
    return NistLevels(
        unit=unit_match.group(1),
        species=species,
        levels=np.array(levels, dtype=np.float64).reshape(-1, 2),
        skipped=skipped,
        limit=min(limits) if limits else None,
        estimated=estimated,
        doubtful=doubtful,
        estimated_mask=np.array(mask, dtype=bool),
    )


# ----------------------------------------------------------------------------------------------------------------------------------
# Automatic download (the levels form as a URL, as used by the former maintain_database.py)
# ----------------------------------------------------------------------------------------------------------------------------------
URL = 'https://physics.nist.gov/cgi-bin/ASD/energy1.pl'
ROMAN_OF = {charge: numeral for numeral, charge in ROMAN.items()}


class NistError(Exception):
    pass


def spectrum_of(species: str) -> str:
    """NIST spectrum of a PICLas species: Ar -> 'Ar I', ArIon1 -> 'Ar II', CIon5 -> 'C VI'"""
    match = re.fullmatch(r'([A-Z][a-z]?)(?:Ion(\d+))?', species)
    if match is None or int(match.group(2) or 0) + 1 not in ROMAN_OF:
        raise NistError(f'{species}: not an atom or atomic ion with a NIST spectrum (e.g. Ar, ArIon1)')
    return f'{match.group(1)} {ROMAN_OF[int(match.group(2) or 0) + 1]}'


def species_of_dataset(dataset: str) -> str:
    """PICLas species of a store dataset: 'levels/arion1' -> 'ArIon1'"""
    match = re.fullmatch(r'levels/([a-z]{1,2})(?:ion(\d+))?', dataset)
    if match is None:
        raise NistError(f'{dataset}: not a NIST levels dataset (levels/<species>, e.g. levels/arion1)')
    return match.group(1).capitalize() + (f'Ion{match.group(2)}' if match.group(2) else '')


def parameters(spectrum: str) -> dict[str, str]:
    """Query of the levels form: the whole table as CSV in cm-1, ordered by energy, with the columns of a manual download"""
    return {
        'de': '0',
        'spectrum': spectrum,
        'units': '0',  # cm-1
        'format': '2',  # CSV
        'output': '0',  # entire table, no pages
        'page_size': '15',
        'multiplet_ordered': '0',  # by energy
        'conf_out': 'on',
        'term_out': 'on',
        'level_out': 'on',
        'unc_out': '1',
        'j_out': 'on',
        'lande_out': 'on',
        'perc_out': 'on',
        'biblio': 'on',
        'temp': '',
        'submit': 'Retrieve Data',
    }


def request(spectrum: str, timeout: float = 120.0, retries: int = 3) -> str:
    """Response of the levels form (the CSV table, or an HTML page with an error message)"""
    import time  # noqa: PLC0415
    import urllib.error  # noqa: PLC0415
    import urllib.parse  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    from piclas_db.common.common_vars import Common  # noqa: PLC0415

    url = f'{URL}?{urllib.parse.urlencode(parameters(spectrum))}'
    headers = {'User-Agent': f'piclas-db/{Common().version} (https://github.com/piclas-framework/piclas-db)'}
    last: Optional[Exception] = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as response:  # noqa: S310 (fixed https host)
                return response.read().decode('utf-8', errors='replace')
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            time.sleep(2.0 * (attempt + 1))
    raise NistError(f'NIST ASD not reachable ({url}): {last}')


def download(species: str) -> tuple[str, str]:
    """Levels of a species from NIST ASD: (file name with the spectrum, e.g. 'NIST-Ar-II.csv', CSV text as received)"""
    spectrum = spectrum_of(species)
    text = request(spectrum)
    if not is_nist_levels(text):
        message = re.sub(r'<[^>]+>', ' ', text)
        message = ' '.join(message.split())[:200]
        raise NistError(f'NIST ASD has no levels for {spectrum}: {message or "empty response"}')
    return f'NIST-{spectrum.replace(" ", "-")}.csv', text
