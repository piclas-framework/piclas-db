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
import ast
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
VELOCITY_UNITS = {'m/s': 1.0, 'cm/s': 1.0e-2, 'a.u.': 2.18769126364e6, 'au': 2.18769126364e6}  # converted with columns.energy.mass_amu
AMU = 1.66053906892e-27  # kg
ELEMENTARY_CHARGE = 1.602176634e-19  # C
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


def default_by() -> Optional[str]:
    """'Name <email>' from the configuration, if set"""
    from piclas_db import config  # noqa: PLC0415

    found = config.identity()
    return f'{found[0]} <{found[1]}>' if found else None


def template(paper: StoreEntry, name: str, page: Optional[str], table: Optional[str], figure: Optional[str], method: str, equation: Optional[str] = None, formula: bool = False, rates: bool = False) -> dict:
    """Extraction record with everything known in advance; the person entering the data completes it"""
    meta = paper.meta
    common = Common()
    return {
        'format': RECORD_FORMAT,
        'format_version': RECORD_VERSION,
        'name': slug(name),
        'data': f'{slug(name)}.formula.yaml' if formula else f'{slug(name)}.csv',
        'created': {
            'date': datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat(),
            'tool': f'piclas-db {common.version}',
            'commit': common.commit or 'unknown',
            'by': default_by(),
        },
        'source': {
            'paper': meta.get('dataset'),
            'reference': meta.get('reference'),
            'doi': meta.get('doi'),
            'file_sha256': meta.get('sha256'),
            'page': page,
            'table': table,
            'figure': figure,
            'equation': equation,
        },
        'method': method,
        'columns': {
            'energy': {'unit': 'eV', 'frame': 'collision'},  # 'lab' needs mass_amu (projectile) and target_mass_amu
            'cross_section': {'unit': '1e-16 cm^2'},
            'uncertainty': {'unit': 'relative', 'optional': True},
        },
        'quantity': {'description': None, 'assignment': {'pair': None, 'kind': None, 'key': None}},
        'accuracy': {'extraction': 'exact (values typed as printed)' if method == 'manual' else None, 'stated_in_source': None},
        'environment': environment(),
        'review': {'status': 'pending', 'reviewer': None, 'date': None, 'notes': None},
        'notes': [],
        **({'formula': True} if formula else {}),
    } | (rate_record() if rates else {})


def rate_record() -> dict:
    """Parts of a record for a reaction rate table (Arrhenius parameters, see rates.py)"""
    return {
        'rate_table': True,
        'columns': {'rate': {'unit': 'cm^3/(mol s)'}, 'temperature': {'unit': 'K'}},
        'quantity': {'description': 'Arrhenius parameters k = C T^n exp(-T_d/T_x)', 'assignment': {'chemistry_model': None}, 'mixture': None},
    }


def load_record(path: Union[str, pathlib.Path]) -> dict:
    path = pathlib.Path(path)
    try:
        head = path.read_bytes()[:5]
    except OSError as e:
        raise LiteratureError(f'cannot read extraction record {path}: {e}') from e
    if head == b'%PDF-':  # a paper given instead of its extraction record
        raise LiteratureError(
            f'{path} is a PDF, not an extraction record (.extraction.yaml). Papers are imported with\n'
            f'  piclas-db import {path} --literature [KEY]\n'
            'and data from a paper with piclas-db extract or literature template, then literature add <name>.extraction.yaml'
        )
    try:
        record = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        raise LiteratureError(f'{path} is not an extraction record (.extraction.yaml): {e}') from e
    if not isinstance(record, dict) or record.get('format') != RECORD_FORMAT:
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


def energy_frame(energy: dict) -> str:
    """'collision' (center-of-mass, what PICLas uses) or 'lab' (projectile energy); velocities are laboratory velocities"""
    unit = str(energy.get('unit', ''))
    default = 'lab' if any(unit.lower().endswith(velocity) for velocity in VELOCITY_UNITS) else 'collision'
    return str(energy.get('frame', default))


def validate_source(record: dict) -> list[str]:
    """Where the data come from: method, paper, page and table/figure/equation"""
    problems = []
    if record.get('method') not in METHODS:
        problems.append(f'method must be one of {", ".join(METHODS)}')
    source = record.get('source') or {}
    if not source.get('file_sha256') and not source.get('doi'):
        problems.append('source: file_sha256 (paper in the store) or doi required')
    if not (source.get('table') or source.get('figure') or source.get('equation')):
        problems.append('source: table, figure or equation required')
    if not source.get('page'):
        problems.append('source: page required')
    return problems


def validate(record: dict, table: Table) -> list[str]:
    """Problems that prevent storing the extraction (empty list: fine)"""
    problems = validate_source(record)
    energy_column = (record.get('columns') or {}).get('energy') or {}
    frame = energy_frame(energy_column)
    if frame not in ('collision', 'lab'):
        problems.append('columns.energy.frame must be "collision" or "lab"')
    elif frame == 'lab' and not all(isinstance(energy_column.get(key), (int, float)) for key in ('mass_amu', 'target_mass_amu')):
        problems.append('columns.energy: laboratory energies or velocities need mass_amu (projectile) and target_mass_amu to give the collision energy PICLas uses')
    if (record.get('review') or {}).get('status', 'pending') not in REVIEW_STATES:
        problems.append(f'review status must be one of {", ".join(REVIEW_STATES)}')
    if np.any(~np.isfinite(table.energy)) or np.any(~np.isfinite(table.cross_section)):
        problems.append('empty or non-numeric energy or cross-section')
    elif np.any(np.diff(table.energy) <= 0.0):
        index = int(np.argmax(np.diff(table.energy) <= 0.0))
        problems.append(f'energies not increasing at row {index + 3} ({table.energy[index]} -> {table.energy[index + 1]}): typing error?')
    negative = table.cross_section < 0.0
    if table.uncertainty is not None:
        # values below zero but zero within their error bar (e.g. a measured zero) are kept and used as zero
        negative &= ~(np.abs(table.cross_section) <= np.nan_to_num(table.uncertainty) * np.abs(table.cross_section))
    if np.any(negative):
        problems.append('negative cross-section (not zero within its uncertainty)')
    try:
        columns = record.get('columns') or {}
        energy = columns.get('energy') or {}
        try:
            unit_factor(str(energy.get('unit', '')), ENERGY_UNITS)
        except LiteratureError:
            unit_factor(str(energy.get('unit', '')), VELOCITY_UNITS)
            if not isinstance(energy.get('mass_amu'), (int, float)):
                problems.append('columns.energy: a velocity needs mass_amu (mass of the projectile) to convert it to an energy')
        unit_factor(str((columns.get('cross_section') or {}).get('unit', '')), AREA_UNITS)
    except LiteratureError as e:
        problems.append(f'{e} (energy units: {", ".join(ENERGY_UNITS)}; velocity units: {", ".join(VELOCITY_UNITS)})')
    return problems


def to_si(record: dict, table: Table) -> np.ndarray:
    """(n_rows, 2): energy [eV], cross-section [m^2]"""
    columns = record['columns']
    unit = str(columns['energy']['unit'])
    try:
        energy = table.energy * unit_factor(unit, ENERGY_UNITS)
    except LiteratureError:
        velocity = table.energy * unit_factor(unit, VELOCITY_UNITS)
        energy = 0.5 * float(columns['energy']['mass_amu']) * AMU * velocity**2 / ELEMENTARY_CHARGE  # kinetic energy in the laboratory frame
    if energy_frame(columns['energy']) == 'lab':
        # PICLas looks cross-sections up at the collision (center-of-mass) energy: E_cm = E_lab m_target / (m_projectile + m_target)
        projectile, target = float(columns['energy']['mass_amu']), float(columns['energy']['target_mass_amu'])
        energy = energy * target / (projectile + target)
    sigma = np.maximum(table.cross_section, 0.0) * unit_factor(str(columns['cross_section']['unit']), AREA_UNITS)
    return np.column_stack([energy, sigma])


def formula_table(record: dict) -> Table:
    from piclas_db.formula import FormulaError, tabulate  # noqa: PLC0415

    try:
        energy, sigma = tabulate(record['formula'])
    except FormulaError as e:
        raise LiteratureError(f'formula: {e}') from e
    return Table(energy, sigma, None)


def read_extraction(entry: StoreEntry) -> np.ndarray:
    """Data of a stored extraction in eV (collision energy) and m^2; formulas are evaluated on their grid"""
    record = entry.meta.get('extraction') or {}
    table = formula_table(record) if record.get('formula') else read_raw(entry.path.read_text(encoding='utf-8'))
    return to_si(record, table)


# ----------------------------------------------------------------------------------------------------------------------------------
# Store
# ----------------------------------------------------------------------------------------------------------------------------------
def papers(store: Store) -> dict[str, StoreEntry]:
    return {str(entry.meta['dataset']): entry for entry in store.entries() if entry.meta.get('provider') == 'literature' and entry.meta.get('kind') == 'paper'}


def extractions(store: Store) -> list[StoreEntry]:
    return [entry for entry in store.entries() if entry.meta.get('provider') == 'literature' and entry.meta.get('kind') == 'extraction']


def read_parameter_table(text: str) -> tuple[list[str], list[list[str]]]:
    """Raw table of parameters (header and rows of text cells, first column: row labels such as 'A 0')"""
    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 2 or len(rows[0]) < 2:
        raise LiteratureError('a parameter table needs a header and at least one row with a label and a value')
    return rows[0], rows[1:]


def label_key(text: str) -> str:
    """Row labels compared without spaces and case: 'A 0' = 'A0', 'I n (eV )' = 'In(eV)'"""
    return re.sub(r'\s+', '', text).lower()


def resolve_parameters(store: Store, formula: dict) -> dict:
    """Parameters of a formula taken from a stored parameter table (one column), frozen into the formula with the table's sha256"""
    from piclas_db.extract.table import parse_number  # noqa: PLC0415
    from piclas_db.formula import FUNCTIONS  # noqa: PLC0415

    source = formula.get('parameters_from')
    if not source:
        return formula
    entry = find_extraction(store, str(source.get('table', '')))
    if not (entry.meta.get('extraction') or {}).get('parameter_table'):
        raise LiteratureError(f'{source.get("table")} is not a parameter table')
    header, rows = read_parameter_table(entry.path.read_text(encoding='utf-8'))
    column = source.get('column')
    if isinstance(column, int):
        index = column  # 1 = first value column
    else:
        matches = [i for i, title in enumerate(header) if i > 0 and label_key(title) == label_key(str(column))]
        if not matches:
            raise LiteratureError(f'column {column!r} not in {source.get("table")} (columns: {", ".join(header[1:])})')
        index = matches[0]
    if not 1 <= index < len(header):
        raise LiteratureError(f'column {column} not in {source.get("table")} ({len(header) - 1} value columns)')
    names = {node.id for node in ast.walk(ast.parse(str(formula.get('expression', '0')).replace('^', '**'), mode='eval')) if isinstance(node, ast.Name)}
    wanted = sorted(names - {'E'} - set(FUNCTIONS) - set(formula.get('parameters') or {}))
    mapping = {str(k): str(v) for k, v in (source.get('rows') or {}).items()}
    by_label = {label_key(row[0]): row for row in rows if row}
    parameters = dict(formula.get('parameters') or {})
    for name in wanted:
        row = by_label.get(label_key(mapping.get(name, name)))
        value = parse_number(row[index]) if row is not None and index < len(row) else None
        if value is None:
            raise LiteratureError(f'parameter {name}: no number in row {mapping.get(name, name)!r}, column {header[index]!r} of {source.get("table")} (rows: {", ".join(r[0] for r in rows)})')
        parameters[name] = value
    return {**formula, 'parameters': parameters, 'parameters_from': {**source, 'column': header[index], 'sha256': entry.meta.get('sha256')}}


def add_extraction(store: Store, record_path: pathlib.Path, by: Optional[str] = None) -> StoreEntry:
    """Validate an extraction (record + raw CSV next to it) and store it; the paper must be in the store"""
    from piclas_db.sources.identify import Identified  # noqa: PLC0415

    record, data_path, table = check_extraction(store, record_path, by)
    if not record.get('parameter_table') and not record.get('rate_table') and not record.get('raw_table'):
        record.setdefault('result', {})['rows'] = len(table.energy)
    zeroed = int(np.sum(table.cross_section < 0.0))
    if zeroed:
        record.setdefault('notes', []).append(f'{zeroed} value(s) below zero but zero within the uncertainty: used as zero')
    paper_name = record['source']['paper']
    identified = Identified(provider='literature', kind='extraction', dataset=f'{paper_name}/{record["name"]}', details={'extraction': record})
    created = datetime.date.fromisoformat(str(record['created']['date'])[:10]) if record.get('created', {}).get('date') else None
    return store.add(data_path, identified, retrieved=created, by=by)


def check_extraction(store: Store, record_path: pathlib.Path, by: Optional[str] = None) -> tuple[dict, pathlib.Path, Table]:
    """Validate an extraction without storing it (literature add -n): the record, its data file and the data read from it; raises
    LiteratureError with all problems"""
    record = load_record(record_path)
    if by and not (record.get('created') or {}).get('by'):
        record.setdefault('created', {})['by'] = by  # who extracted the data, if the record does not say
    data_path = record_path.parent / str(record.get('data', ''))
    if not data_path.is_file():
        raise LiteratureError(f'data file not found: {data_path}')
    if record.get('rate_table'):
        from piclas_db.rates import RateError, read_rate_table, validate_rate_table  # noqa: PLC0415

        try:
            rate_rows = read_rate_table(data_path.read_text(encoding='utf-8'))
        except RateError as e:
            raise LiteratureError(f'{data_path}: {e}') from e
        problems = validate_source(record) + validate_rate_table(record, rate_rows)
        table = Table(np.zeros(0), np.zeros(0), None)
        record.setdefault('result', {}).update({'rows': len(rate_rows), 'reactions': len({str(row.key) for row in rate_rows})})
    elif record.get('raw_table'):  # raw copy of a reaction table: kept as printed, not used by builds
        with data_path.open(encoding='utf-8') as file:
            count = max(sum(1 for line in file if line.strip()) - 1, 0)
        problems = validate_source(record)
        table = Table(np.zeros(0), np.zeros(0), None)
        record.setdefault('result', {}).update({'rows': count})
    elif record.get('parameter_table'):
        header, rows = read_parameter_table(data_path.read_text(encoding='utf-8'))
        problems = validate_source(record)
        table = Table(np.zeros(0), np.zeros(0), None)
        record.setdefault('result', {}).update({'rows': len(rows), 'columns': header[1:]})
    elif record.get('formula'):
        formula = yaml.safe_load(data_path.read_text(encoding='utf-8')) or {}  # the stored file is the formula itself
        record['formula'] = resolve_parameters(store, formula)
        record['method'] = record.get('method') or 'manual'
        table = formula_table(record)
        problems = validate(record, table)
    else:
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
    return record, data_path, table


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
