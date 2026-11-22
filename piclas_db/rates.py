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
"""Reaction rate tables from papers (Arrhenius parameters k = C T^n exp(-T_d/T)) and their comparison with the reactions of an existing
database.

A rate table is a literature extraction (record with `rate_table: true`) whose CSV holds the rows as printed:

    row,reaction,third_body,C,n,Td,Tx
    1,N2 + M -> N + N + M,N,3.0e22,-1.6,113200,Ta
    1,N2 + M -> N + N + M,"N2, O2",7.0e21,-1.6,113200,Ta
    11,N2 + O -> NO + N,,6.4e17,-1.0,38400,T

`C` is in the unit of the record (`columns.rate.unit`, e.g. `cm^3/(mol s)`, generalized to the order of the reaction: a termolecular
recombination in such a table is in cm^6/(mol^2 s)); species are written as printed (N2+, NO+, C+, e-), third bodies as M or A with
the species of the row in `third_body` (one species, a comma-separated list, `molecules`, `atoms`, `others` or `all`).

`explain_reactions` compares every reaction of a database with all stored rate tables: per chemistry model of the reaction it says
whether the paper of that model (record `quantity.assignment.chemistry_model`, e.g. `Park1993` for `Air_11Spec_27Reac_Park1993`)
has the same C, n and T_d, and which other tables do.
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import csv
import io
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.model import Database
from piclas_db.store import Store
# ==================================================================================================================================

AVOGADRO = 6.02214076e23
RATE_UNITS = {  # factor to PICLas (m^3/s per molecule) for a bimolecular rate; applied (order - 1) times
    'cm^3/(mol s)': 1.0e-6 / AVOGADRO,
    'cm3/mol/s': 1.0e-6 / AVOGADRO,
    'm^3/(mol s)': 1.0 / AVOGADRO,
    'm^3/(molecule s)': 1.0,
    'm3/molecule/s': 1.0,
    'cm^3/(molecule s)': 1.0e-6,
    'cm^3/s': 1.0e-6,
    'cm3/s': 1.0e-6,
}
CONTROLLING = ('T', 'Ta', 'Tv', 'Te', 'Tve', 'Ttr')
THIRD_BODY = ('M', 'A')
C_TOLERANCE = 6.0e-3  # relative: databases often keep 3 significant digits of the converted prefactor
COLUMNS = ['row', 'reaction', 'third_body', 'C', 'n', 'Td', 'Tx']
CLASSES = ('molecules', 'atoms', 'others', 'all')  # third bodies by class: molecules and atoms include their ions, not the electron


class RateError(Exception):
    pass


def species_name(printed: str) -> str:
    """PICLas name of a species as printed: N2+ -> N2Ion1, O++ -> OIon2, C+6 -> CIon6, e-/e/E- -> electron"""
    text = printed.strip().replace('−', '-').replace('⁺', '+')
    if text in ('e', 'e-', 'E-', 'E', 'electron', 'el'):
        return 'electron'
    if text in THIRD_BODY:
        return text
    match = re.fullmatch(r'([A-Za-z][A-Za-z0-9]*?)(\+*)(\d*)', text)
    if match is None:
        raise RateError(f'species {printed!r} not understood')
    base, pluses, count = match.groups()
    charge = int(count) if count and pluses == '+' else len(pluses)
    if count and not pluses:
        base, charge = base + count, 0
    return f'{base}Ion{charge}' if charge else base


def split_reaction(text: str) -> tuple[list[str], list[str]]:
    """Reactants and products (PICLas names, third bodies kept as M/A) of 'N2 + M -> N + N + M' (also →, ⇔, =)"""
    parts = re.split(r'\s*(?:->|→|⇔|<=>|=)\s*', text.strip())
    if len(parts) != 2:
        raise RateError(f'reaction {text!r}: need reactants -> products')
    reactants, products = ([species_name(item) for item in re.split(r'\s+\+\s+', side.strip()) if item.strip()] for side in parts)
    return reactants, products


@dataclass(frozen=True)
class Key:
    """Reaction without its third body: sorted reactants and products"""

    reactants: tuple[str, ...]
    products: tuple[str, ...]

    def __str__(self) -> str:
        return ' + '.join(self.reactants) + ' -> ' + ' + '.join(self.products)


def canonical(reactants: list[str], products: list[str]) -> tuple[Key, Optional[str]]:
    """Key and explicit third body: a species on both sides once (N2 + Ar -> N + N + Ar: Ar), M/A removed"""
    left, right = Counter(r for r in reactants if r not in THIRD_BODY), Counter(p for p in products if p not in THIRD_BODY)
    common = left & right
    body: Optional[str] = None
    if 'M' in reactants or 'A' in reactants:
        body = 'M'
    elif sum(common.values()) == 1:
        body = next(iter(common))
        left, right = left - common, right - common
    return Key(tuple(sorted(left.elements())), tuple(sorted(right.elements()))), body


@dataclass
class RateRow:
    row: str
    reaction: str
    key: Key
    third_bodies: tuple[str, ...]  # PICLas names or classes (molecules, atoms, others, all); () without third body
    C: float
    n: float
    Td: float
    Tx: str
    order: int

    def prefactor(self, unit: str) -> float:
        """C in PICLas units (m^3/s per molecule, m^6/s for termolecular reactions)"""
        return self.C * RATE_UNITS[unit] ** (self.order - 1)


def parse_number(text: str) -> float:
    """3.0e22, 3.0E+22, 3.0^22 (printed superscript exponent), 3.0x10^22, 3.0×10^22"""
    value = text.strip().replace('×', 'x').replace('−', '-').replace(' ', '')
    match = re.fullmatch(r'([-+]?\d*\.?\d+)(?:x10\^?|\^)([-+]?\d+)', value)
    if match:
        return float(match.group(1)) * 10.0 ** int(match.group(2))
    return float(value)


def read_rate_table(text: str) -> list[RateRow]:
    """Rows of a rate table CSV (comment lines start with '#'); errors name the row"""
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    reader = list(csv.DictReader(io.StringIO('\n'.join(lines))))
    if not reader:
        raise RateError('a rate table needs a header and at least one row')
    missing = [column for column in COLUMNS if column not in (reader[0].keys() or [])]
    if missing:
        raise RateError(f'columns missing: {", ".join(missing)} (header: {",".join(COLUMNS)})')
    rows = []
    for number, cells in enumerate(reader, start=2):
        try:
            reactants, products = split_reaction(cells['reaction'])
            key, body = canonical(reactants, products)
            printed = [part.strip() for part in (cells.get('third_body') or '').split(',') if part.strip()]
            if body == 'M':
                bodies = tuple(part.lower() if part.lower() in CLASSES else species_name(part) for part in printed) or ('all',)
            elif body:
                bodies = (body,)
            else:
                bodies = ()
            tx = (cells.get('Tx') or 'T').strip()
            if tx not in CONTROLLING:
                raise RateError(f'Tx {tx!r} not one of {", ".join(CONTROLLING)}')
            td = (cells.get('Td') or '').strip()
            rows.append(
                RateRow(
                    row=str(cells.get('row') or '').strip(),
                    reaction=cells['reaction'].strip(),
                    key=key,
                    third_bodies=bodies,
                    C=parse_number(cells['C']),
                    n=parse_number(cells.get('n') or '0'),
                    Td=parse_number(td) if td else 0.0,
                    Tx=tx,
                    order=len(key.reactants) + (1 if bodies else 0),
                )
            )
        except (RateError, ValueError, KeyError) as e:
            raise RateError(f'row {number}: {e}') from e
    return rows


def validate_rate_table(record: dict, rows: list[RateRow]) -> list[str]:
    problems = []
    unit = str(((record.get('columns') or {}).get('rate') or {}).get('unit', ''))
    if unit not in RATE_UNITS:
        problems.append(f'columns.rate.unit {unit!r} unknown ({", ".join(RATE_UNITS)})')
    problems.extend(f'row {row.row} ({row.reaction}): C must be positive' for row in rows if row.C <= 0.0)
    return problems


# ----------------------------------------------------------------------------------------------------------------------------------
# Comparison with a database
# ----------------------------------------------------------------------------------------------------------------------------------
@dataclass
class Table:
    name: str  # literature/<paper>/<dataset>
    chemistry_model: Optional[str]  # suffix of the chemistry models taken from this paper, e.g. Park1993
    unit: str
    rows: list[RateRow]
    approved: bool = False


@dataclass
class ModelCheck:
    model: str
    status: str  # match, differs, missing (reaction or third body not in the paper), no table (paper not extracted)
    details: list[str] = field(default_factory=list)


@dataclass
class ReactionExplanation:
    name: str
    C: float
    n: float
    Td: float
    checks: list[ModelCheck] = field(default_factory=list)
    found_in: list[str] = field(default_factory=list)  # tables (and rows) with the same values, whatever the model


def same(row: RateRow, unit: str, C: float, n: float, Td: float) -> list[str]:
    """Differences between a table row and database values (empty: same)"""
    differences = []
    expected = row.prefactor(unit)
    if abs(C - expected) > C_TOLERANCE * abs(expected):
        differences.append(f'C {C:.4g} vs. {expected:.4g} ({C / expected:.4g}x)')
    if abs(n - row.n) > 1.0e-3:
        differences.append(f'n {n:+.3f} vs. {row.n:+.3f}')
    if abs(Td - row.Td) > max(1.0, 1.0e-4 * row.Td):
        differences.append(f'T_d {Td:.0f} vs. {row.Td:.0f}')
    return differences


def rounded(value: float, exact: float) -> bool:
    """value is exact rounded to 3 to 5 significant digits (or equal to 1e-4): the usual storage of a converted prefactor"""
    return abs(value / exact - 1.0) < 1.0e-4 or any(math.isclose(float(f'{exact:.{digits - 1}e}'), float(f'{value:.{digits - 1}e}'), rel_tol=1.0e-12) for digits in (3, 4, 5))


def rows_for(table: Table, key: Key, body: Optional[str]) -> list[RateRow]:
    """Rows of a table for a reaction and one third body (explicit species, then 'others'/'all')"""
    rows = [row for row in table.rows if row.key == key and bool(row.third_bodies) == bool(body)]
    if not body:
        return rows
    exact = [row for row in rows if body in row.third_bodies]
    if exact:
        return exact
    kind = species_class(body)
    by_class = [row for row in rows if kind and kind in row.third_bodies]
    return by_class or [row for row in rows if 'others' in row.third_bodies or 'all' in row.third_bodies]


def species_class(name: str) -> Optional[str]:
    """'molecules' or 'atoms' (ions by their composition), None for the electron and unknown names"""
    from piclas_db.atct_map import piclas_name  # noqa: PLC0415

    parsed = piclas_name(name) if name != 'electron' else None
    if parsed is None:
        return None
    return 'atoms' if sum(parsed[1].values()) == 1 else 'molecules'


def as_float(value: object) -> float:
    return float(value) if isinstance(value, (int, float, str)) else 0.0


def as_list(value: object) -> list:
    return list(value) if isinstance(value, (list, tuple)) else []


def explain_reactions(database: Database, tables: list[Table]) -> list[ReactionExplanation]:
    results = []
    for name, reaction in sorted(database.reactions.items()):
        attributes = reaction.attributes
        if 'Arrhenius-Prefactor' not in attributes:
            continue  # QK reactions carry no Arrhenius parameters
        C, n, Td = (as_float(attributes.get(key)) for key in ('Arrhenius-Prefactor', 'Arrhenius-Powerfactor', 'Activation-Energy_K'))
        reactants, products = [str(s) for s in as_list(attributes.get('Reactants'))], [str(s) for s in as_list(attributes.get('Products'))]
        stem = name.split('_')[0].split('+')
        generic = 'M' in stem or 'A' in stem  # third body given per chemistry model (non-reactive species)
        key, explicit = canonical(reactants, products)
        result = ReactionExplanation(name, C, n, Td)
        found: dict[str, list[str]] = {}
        for table in tables:
            for row in table.rows:
                if row.key == key and not same(row, table.unit, C, n, Td):
                    bodies = found.setdefault(f'{table.name} row {row.row}', [])
                    bodies += [body for body in row.third_bodies if body not in bodies]
        result.found_in = [label + (f' ({", ".join(bodies)})' if bodies else '') for label, bodies in found.items()]
        for model in as_list(attributes.get('ChemistryModel')):
            model_name = str(model[0]) if isinstance(model, list) else str(model)
            bodies = [s for s in (str(model[1]).split(',') if isinstance(model, list) and len(model) > 1 else []) if s] if generic else ([explicit] if explicit else [None])
            paper = [table for table in tables if table.chemistry_model and model_name.endswith('_' + table.chemistry_model)]
            if not paper:
                result.checks.append(ModelCheck(model_name, 'no table'))
                continue
            grouped: dict[str, list[str]] = {}  # message -> third bodies with it
            worst = 'match'
            for body in bodies or [None]:
                candidates = [(table, row) for table in paper for row in rows_for(table, key, body)]
                if not candidates:
                    grouped.setdefault('not in the table', []).append(body or '')
                    worst = 'missing' if worst == 'match' else worst
                    continue
                differences = [same(row, table.unit, C, n, Td) for table, row in candidates]
                matching = [(table, row) for (table, row), d in zip(candidates, differences, strict=True) if not d]
                if matching:
                    table, row = matching[0]
                    expected = row.prefactor(table.unit)
                    if not rounded(C, expected):
                        grouped.setdefault(f'C {C:.4g} vs. {expected:.4g} ({C / expected - 1.0:+.2%}, within the tolerance; row {row.row})', []).append(body or '')
                else:
                    best = min(differences, key=len)
                    grouped.setdefault(f'{"; ".join(best)} (row {candidates[differences.index(best)][1].row})', []).append(body or '')
                    worst = 'differs'
            details = [(', '.join(b for b in group if b) + ': ' if any(group) else '') + message for message, group in grouped.items()]
            result.checks.append(ModelCheck(model_name, worst, details))
        results.append(result)
    return results


def describe(result: ReactionExplanation) -> list[str]:
    lines = [f'{result.name:34s} C={result.C:.4g} n={result.n:+.3f} T_d={result.Td:.0f}']
    lines.extend(f'    {check.status:9s} {check.model}' + (': ' + '; '.join(check.details) if check.details else '') for check in result.checks)
    if result.found_in:
        lines.append('    same values in: ' + ', '.join(result.found_in))
    return lines


def summary(results: list[ReactionExplanation]) -> str:
    counts = Counter(check.status for result in results for check in result.checks)
    orphans = sum(1 for result in results if not result.found_in)
    return f'{len(results)} Arrhenius reactions, {sum(counts.values())} reaction/model pairs: ' + ', '.join(f'{v} {k}' for k, v in counts.most_common()) + f'; {orphans} reactions in no table'


def stored_tables(store: Store) -> list[Table]:
    """All rate tables in the store (reviewed or not: an explanation, not a build, so pending tables are shown too)"""
    from piclas_db.literature import extractions  # noqa: PLC0415

    tables = []
    for entry in extractions(store):
        record = entry.meta.get('extraction') or {}
        if not record.get('rate_table'):
            continue
        assignment = (record.get('quantity') or {}).get('assignment') or {}
        tables.append(
            Table(
                name=f'literature/{entry.meta.get("dataset")}',
                chemistry_model=assignment.get('chemistry_model'),
                unit=str(((record.get('columns') or {}).get('rate') or {}).get('unit')),
                rows=read_rate_table(entry.path.read_text(encoding='utf-8')),
                approved=(record.get('review') or {}).get('status') == 'approved',
            )
        )
    return tables
