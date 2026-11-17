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

The ASD level form exports tables as CSV, tab-separated or formatted text ('|' separated). The header contains the columns
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
    value = re.sub(r'[\[\]()?+a-zA-Z]', '', clean(value)).strip()
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

    levels, skipped = [], 0
    for row in rows[1:]:
        if len(row) <= max(level_column, j_column):
            skipped += 1
            continue
        j, energy = parse_j(row[j_column]), parse_energy(row[level_column])
        if j is None or energy is None:
            skipped += 1
            continue
        levels.append((2.0 * j + 1.0, energy))

    # Spectrum name before the table (the table itself names the next ion in its 'Limit' rows), otherwise from the file name
    species = piclas_species('\n'.join(lines[:header_index])) or piclas_species(name_hint)
    return NistLevels(unit=unit_match.group(1), species=species, levels=np.array(levels, dtype=np.float64).reshape(-1, 2), skipped=skipped)
