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
"""Data from papers ('literature' provider): papers in the store and extracted datasets with an extraction record

A paper (PDF) is an original file in the store: literature/<paper>/<date>_<sha8>.pdf. Data taken from it (a table typed by hand,
or later extracted automatically) is stored next to it as the raw values exactly as printed in the paper (CSV) together with an
extraction record (meta.yaml) that says where the data comes from (paper sha256, page, table or figure), how it was obtained
(method, piclas-db version, environment), in which units it is given, how accurate the extraction is and whether it has been
reviewed. Only reviewed extractions are used by 'build' unless explicitly allowed.

    literature/<paper>/<dataset>/<created>_<sha8>.csv        raw values as printed (energy, cross-section[, uncertainty])
    literature/<paper>/<dataset>/<created>_<sha8>.csv.meta.yaml   extraction record
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import csv
import datetime
import io
import pathlib
import platform
import re
from dataclasses import dataclass
from typing import Optional, Union

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import numpy as np
import yaml

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.common.common_vars import Common
from piclas_db.sources.identify import slug
from piclas_db.store import Store, StoreEntry
# ==================================================================================================================================

RECORD_FORMAT = 'piclas-db extraction record'
RECORD_VERSION = 1
METHODS = ('manual', 'text', 'ocr', 'vector', 'raster')
REVIEW_STATES = ('pending', 'approved', 'rejected')
BOHR_RADIUS = 5.29177210544e-11  # m

ENERGY_UNITS = {'ev': 1.0, 'mev': 1.0e-3, 'kev': 1.0e3}
AREA_UNITS = {
    'm^2': 1.0,
    'm2': 1.0,
    'cm^2': 1.0e-4,
    'cm2': 1.0e-4,
    'a^2': 1.0e-20,
    'å^2': 1.0e-20,
    'angstrom^2': 1.0e-20,
    'a0^2': BOHR_RADIUS**2,
    'pi a0^2': np.pi * BOHR_RADIUS**2,
}


class LiteratureError(Exception):
    """Invalid extraction or paper"""


def unit_factor(text: str, units: dict[str, float]) -> float:
    """Factor to SI-like base units (eV, m^2) of a unit such as '1e-16 cm^2', '10^-17 cm2', 'keV'"""
    cleaned = text.strip().lower().replace('**', '^').replace('×', ' ').replace('x10', '1e').replace('10^', '1e')
    match = re.fullmatch(r'([-+]?\d*\.?\d+(?:e[-+]?\d+)?)?\s*\*?\s*(.+)', cleaned)
    if not match or match.group(2).strip() not in units:
        raise LiteratureError(f'unknown unit {text!r} (known: {", ".join(units)}, optionally with a factor such as "1e-16 cm^2")')
    return (float(match.group(1)) if match.group(1) else 1.0) * units[match.group(2).strip()]


# ----------------------------------------------------------------------------------------------------------------------------------
# Extraction records
# ----------------------------------------------------------------------------------------------------------------------------------
def environment() -> dict[str, str]:
    return {'python': platform.python_version(), 'numpy': np.__version__, 'platform': platform.platform(terse=True)}


def template(paper: StoreEntry, name: str, page: Optional[str], table: Optional[str], figure: Optional[str], method: str) -> dict:
    """Extraction record with everything known in advance; the person entering the data completes it"""
    meta = paper.meta
    common = Common()
    return {
        'format': RECORD_FORMAT,
        'format_version': RECORD_VERSION,
        'name': slug(name),
        'data': f'{slug(name)}.csv',
        'created': {
            'date': datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat(),
            'tool': f'piclas-db {common.version}',
            'commit': common.commit or 'unknown',
            'by': None,
        },
        'source': {
            'paper': meta.get('dataset'),
            'reference': meta.get('reference'),
            'doi': meta.get('doi'),
            'file_sha256': meta.get('sha256'),
            'page': page,
            'table': table,
            'figure': figure,
        },
        'method': method,
        'columns': {'energy': {'unit': 'eV'}, 'cross_section': {'unit': '1e-16 cm^2'}, 'uncertainty': {'unit': 'relative', 'optional': True}},
        'quantity': {'description': None, 'assignment': {'pair': None, 'kind': None, 'key': None}},
        'accuracy': {'extraction': 'exact (values typed as printed)' if method == 'manual' else None, 'stated_in_source': None},
        'environment': environment(),
        'review': {'status': 'pending', 'reviewer': None, 'date': None, 'notes': None},
        'notes': [],
    }


def load_record(path: Union[str, pathlib.Path]) -> dict:
    path = pathlib.Path(path)
    try:
        record = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    except (OSError, yaml.YAMLError) as e:
        raise LiteratureError(f'cannot read extraction record {path}: {e}') from e
    if record.get('format') != RECORD_FORMAT:
        raise LiteratureError(f'{path}: not a piclas-db extraction record')
    if int(record.get('format_version', 0)) > RECORD_VERSION:
        raise LiteratureError(f'{path}: record format version {record["format_version"]} is newer than supported ({RECORD_VERSION})')
    return record


@dataclass
class Table:
    energy: np.ndarray  # as printed
    cross_section: np.ndarray  # as printed
    uncertainty: Optional[np.ndarray]


def read_raw(text: str) -> Table:
    """Raw CSV: header line, then energy, cross-section[, uncertainty]; comment lines start with '#'"""
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    rows = list(csv.reader(io.StringIO('\n'.join(lines))))
    if len(rows) < 3:
        raise LiteratureError('at least a header and two data rows are needed')
    values = []
    for number, row in enumerate(rows[1:], start=2):
        try:
            values.append([float(cell) if cell.strip() else np.nan for cell in row])
        except ValueError as e:
            raise LiteratureError(f'row {number}: not a number in {row}') from e
    width = {len(row) for row in values}
    if len(width) != 1 or width.pop() not in (2, 3):
        raise LiteratureError('every row needs two or three columns (energy, cross-section[, uncertainty])')
    array = np.array(values)
    return Table(array[:, 0], array[:, 1], array[:, 2] if array.shape[1] == 3 else None)


def validate(record: dict, table: Table) -> list[str]:
    """Problems that prevent storing the extraction (empty list: fine)"""
    problems = []
    if record.get('method') not in METHODS:
        problems.append(f'method must be one of {", ".join(METHODS)}')
    source = record.get('source') or {}
    if not source.get('file_sha256') and not source.get('doi'):
        problems.append('source: file_sha256 (paper in the store) or doi required')
    if not (source.get('table') or source.get('figure')):
        problems.append('source: table or figure required')
    if not source.get('page'):
        problems.append('source: page required')
    if (record.get('review') or {}).get('status', 'pending') not in REVIEW_STATES:
        problems.append(f'review status must be one of {", ".join(REVIEW_STATES)}')
    if np.any(~np.isfinite(table.energy)) or np.any(~np.isfinite(table.cross_section)):
        problems.append('empty or non-numeric energy or cross-section')
    elif np.any(np.diff(table.energy) <= 0.0):
        index = int(np.argmax(np.diff(table.energy) <= 0.0))
        problems.append(f'energies not increasing at row {index + 3} ({table.energy[index]} -> {table.energy[index + 1]}): typing error?')
    if np.any(table.cross_section < 0.0):
        problems.append('negative cross-section')
    try:
        columns = record.get('columns') or {}
        unit_factor(str((columns.get('energy') or {}).get('unit', '')), ENERGY_UNITS)
        unit_factor(str((columns.get('cross_section') or {}).get('unit', '')), AREA_UNITS)
    except LiteratureError as e:
        problems.append(str(e))
    return problems


def to_si(record: dict, table: Table) -> np.ndarray:
    """(n_rows, 2): energy [eV], cross-section [m^2]"""
    columns = record['columns']
    energy = table.energy * unit_factor(str(columns['energy']['unit']), ENERGY_UNITS)
    sigma = table.cross_section * unit_factor(str(columns['cross_section']['unit']), AREA_UNITS)
    return np.column_stack([energy, sigma])


def read_extraction(entry: StoreEntry) -> np.ndarray:
    """Data of a stored extraction in eV and m^2"""
    record = entry.meta.get('extraction') or {}
    return to_si(record, read_raw(entry.path.read_text(encoding='utf-8')))


# ----------------------------------------------------------------------------------------------------------------------------------
# Store
# ----------------------------------------------------------------------------------------------------------------------------------
def papers(store: Store) -> dict[str, StoreEntry]:
    return {str(entry.meta['dataset']): entry for entry in store.entries() if entry.meta.get('provider') == 'literature' and entry.meta.get('kind') == 'paper'}


def extractions(store: Store) -> list[StoreEntry]:
    return [entry for entry in store.entries() if entry.meta.get('provider') == 'literature' and entry.meta.get('kind') == 'extraction']


def add_extraction(store: Store, record_path: pathlib.Path) -> StoreEntry:
    """Validate an extraction (record + raw CSV next to it) and store it; the paper must be in the store"""
    from piclas_db.sources.identify import Identified  # noqa: PLC0415

    record = load_record(record_path)
    data_path = record_path.parent / str(record.get('data', ''))
    if not data_path.is_file():
        raise LiteratureError(f'data file not found: {data_path}')
    table = read_raw(data_path.read_text(encoding='utf-8'))
    problems = validate(record, table)
    paper_name = (record.get('source') or {}).get('paper')
    known = papers(store)
    if paper_name not in known:
        problems.append(f'paper {paper_name!r} not in the store (piclas-db import <pdf> --literature {paper_name or "<key>"} --doi ...)')
    elif known[paper_name].meta.get('sha256') != record['source'].get('file_sha256'):
        problems.append(f'file_sha256 does not match the paper {paper_name} in the store')
    if problems:
        raise LiteratureError('; '.join(problems))
    record.setdefault('result', {})['rows'] = len(table.energy)
    identified = Identified(provider='literature', kind='extraction', dataset=f'{paper_name}/{record["name"]}', details={'extraction': record})
    created = datetime.date.fromisoformat(str(record['created']['date'])[:10]) if record.get('created', {}).get('date') else None
    return store.add(data_path, identified, retrieved=created)


def find_extraction(store: Store, name: str) -> StoreEntry:
    """Extraction by '<paper>/<dataset>' (newest) or '<paper>/<dataset>@<sha prefix>'"""
    dataset, _, checksum = name.removeprefix('literature/').partition('@')
    matches = [entry for entry in extractions(store) if entry.meta.get('dataset') == dataset and str(entry.meta.get('sha256', '')).startswith(checksum)]
    if not matches:
        raise LiteratureError(f'no extraction {name} in the store')
    return max(matches, key=lambda entry: str((entry.meta.get('extraction') or {}).get('created', {}).get('date', '')))


def review(store: Store, entry: StoreEntry, status: str, reviewer: str, notes: Optional[str]) -> None:
    """Record a review; the data stay unchanged, only the extraction record in the meta file is updated (and committed)"""
    if status not in REVIEW_STATES:
        raise LiteratureError(f'review status must be one of {", ".join(REVIEW_STATES)}')
    entry.meta['extraction']['review'] = {
        'status': status,
        'reviewer': reviewer,
        'date': datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat(),
        'notes': notes,
    }
    store.update_meta(entry, f'Review {entry.meta.get("dataset")}: {status} by {reviewer}')
