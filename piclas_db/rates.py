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
from piclas_db.resolve import Requirement
from piclas_db.store import Store, StoreEntry
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
        tables.append(table_from_entry(entry))
    return tables


# ----------------------------------------------------------------------------------------------------------------------------------
# Reactions in recipes: built from rate tables
# ----------------------------------------------------------------------------------------------------------------------------------
@dataclass
class ReactionSpec:
    """One reaction of the database (one HDF5 entry), shared by one or more chemistry models.

    TCE reactions take C, n and T_d from a rate table in the store (`rates`, the table row `row` and, where the table has a row per
    third body, `third_body`) or from `arrhenius` (PICLas units, with `reference`); QK reactions need neither.
    """

    name: str
    reactants: list[str]
    products: list[str]
    models: list[tuple[str, Optional[str]]]  # chemistry model and its non-reactive species (third bodies), None without
    model: str = 'TCE'
    rates: Optional[Requirement] = None
    row: Optional[str] = None
    third_body: Optional[str] = None
    arrhenius: Optional[dict[str, float]] = None  # C (m^3/s per molecule), n, Td (K)
    reference: Optional[str] = None


REACTION_KEYS = {'reaction', 'reactants', 'products', 'model', 'rates', 'row', 'third_body', 'arrhenius', 'reference', 'models'}


def is_reaction_spec(attributes: dict) -> bool:
    """New-style recipe entry (from a rate table or with arrhenius), as opposed to raw PICLas attributes"""
    return bool(set(attributes) & {'reaction', 'reactants', 'rates', 'arrhenius', 'models'})


def parse_reaction_spec(name: str, data: dict) -> ReactionSpec:
    unknown = set(data) - REACTION_KEYS
    if unknown:
        raise RateError(f'reactions/{name}: unknown keys {", ".join(sorted(unknown))} ({", ".join(sorted(REACTION_KEYS))})')
    if data.get('reaction'):
        reactants, products = split_reaction(str(data['reaction']))
        reactants, products = [s for s in reactants if s not in THIRD_BODY], [s for s in products if s not in THIRD_BODY]
    else:
        reactants, products = [str(s) for s in data.get('reactants') or []], [str(s) for s in data.get('products') or []]
    if not reactants or not products:
        raise RateError(f'reactions/{name}: "reaction" (N2 + M -> N + N + M) or "reactants" and "products" required')
    models_data = data.get('models') or {}
    if not isinstance(models_data, dict) or not models_data:
        raise RateError(f'reactions/{name}: "models" (chemistry model: non-reactive species or null) required')
    models = [(str(model), None if bodies is None else (','.join(map(str, bodies)) if isinstance(bodies, list) else str(bodies))) for model, bodies in models_data.items()]
    spec = ReactionSpec(name=name, reactants=reactants, products=products, models=models, model=str(data.get('model', 'TCE')))
    if data.get('rates'):
        try:
            spec.rates = Requirement.parse(str(data['rates']))
        except ValueError as e:
            raise RateError(f'reactions/{name}: rates: {e}') from e
    spec.row = None if data.get('row') is None else str(data['row'])
    spec.third_body = None if data.get('third_body') is None else str(data['third_body'])
    spec.reference = None if data.get('reference') is None else str(data['reference'])
    if data.get('arrhenius') is not None:
        values = data['arrhenius']
        if not isinstance(values, dict) or not {'C', 'n', 'Td'} <= set(values):
            raise RateError(f'reactions/{name}: arrhenius needs C (m^3/s), n and Td (K)')
        spec.arrhenius = {key: float(values[key]) for key in ('C', 'n', 'Td')}
    if spec.model == 'TCE' and (spec.rates is None) == (spec.arrhenius is None):
        raise RateError(f'reactions/{name}: a TCE reaction needs either "rates" (a rate table) or "arrhenius" (with "reference")')
    if spec.model != 'TCE' and (spec.rates or spec.arrhenius):
        raise RateError(f'reactions/{name}: {spec.model} reactions carry no Arrhenius parameters')
    return spec


def spec_row(spec: ReactionSpec, table: Table) -> RateRow:
    """The table row of a reaction: same reactants and products, the given row label and third body"""
    key, explicit = canonical(spec.reactants, spec.products)
    generic = any(bodies for _, bodies in spec.models)
    body = spec.third_body or (str(spec.models[0][1]).split(',')[0] if generic else explicit)
    if spec.third_body:
        body = species_name(spec.third_body) if spec.third_body.lower() not in CLASSES else spec.third_body.lower()
    rows = [row for row in table.rows if row.key == key and (spec.row is None or row.row == spec.row)]
    if body in CLASSES:
        rows = [row for row in rows if body in row.third_bodies]
    elif body is not None and any(row.third_bodies for row in rows):
        selected = Table(table.name, table.chemistry_model, table.unit, rows)
        rows = rows_for(selected, key, body)
    if not rows:
        raise RateError(f'reactions/{spec.name}: no row in {table.name} for {key}' + (f' (row {spec.row})' if spec.row else '') + (f' with third body {body}' if body else ''))
    return rows[0]


def build_reaction(spec: ReactionSpec, table: Optional[Table], citation: Optional[str], notes: list[str]) -> tuple[dict[str, object], str]:
    """PICLas attributes of a reaction and its reference; notes for third bodies whose table rate differs from the one used"""
    attributes: dict[str, object] = {'Reactants': list(spec.reactants), 'Products': list(spec.products), 'ReactionModel': [spec.model]}
    with_bodies = any(bodies is not None for _, bodies in spec.models)
    attributes['ChemistryModel'] = [[model, bodies or ''] if with_bodies else [model] for model, bodies in spec.models]
    reference = spec.reference or ''
    if spec.model == 'TCE':
        if table is not None:
            row = spec_row(spec, table)
            C, n, Td = row.prefactor(table.unit), row.n, row.Td
            reference = f'{citation}, row {row.row}' + (' (' + ', '.join(row.third_bodies) + ')' if row.third_bodies else '')
            key = row.key
            for model, bodies in spec.models:
                if not (table.chemistry_model and model.endswith('_' + table.chemistry_model)):
                    continue  # third bodies are checked against the paper of their own model only (rebuild --explain does the rest)
                others = []
                for body in (bodies or '').split(','):
                    if body and body not in row.third_bodies:
                        candidates = rows_for(table, key, body)
                        differences = same(candidates[0], table.unit, C, n, Td) if candidates else []
                        if differences:
                            others.append(f'{body} (row {candidates[0].row}: ' + '; '.join(differences) + ')')
                if others:
                    notes.append(f'{spec.name} ({model}): the table gives another rate for ' + ', '.join(others))
        else:
            assert spec.arrhenius is not None
            C, n, Td = spec.arrhenius['C'], spec.arrhenius['n'], spec.arrhenius['Td']
            reference = reference or 'source unknown'
        attributes.update({'Arrhenius-Prefactor': C, 'Arrhenius-Powerfactor': n, 'Activation-Energy_K': Td})
    return attributes, reference


def table_from_entry(entry: StoreEntry) -> Table:
    record = entry.meta.get('extraction') or {}
    assignment = (record.get('quantity') or {}).get('assignment') or {}
    return Table(
        name=f'literature/{entry.meta.get("dataset")}',
        chemistry_model=assignment.get('chemistry_model'),
        unit=str(((record.get('columns') or {}).get('rate') or {}).get('unit')),
        rows=read_rate_table(entry.path.read_text(encoding='utf-8')),
        approved=(record.get('review') or {}).get('status') == 'approved',
    )


def specs_from_database(database: Database, tables: list[Table]) -> tuple[dict[str, ReactionSpec], dict[str, str], list[str]]:
    """Reaction specs for every reaction of an existing database (rebuild): a rate table row with the same C, n and T_d (preferably
    from the paper of one of the reaction's chemistry models), else the database's own values with 'source unknown'"""
    specs: dict[str, ReactionSpec] = {}
    notes: list[str] = []
    for name, reaction in database.reactions.items():
        attributes = reaction.attributes
        reactants, products = [str(s) for s in as_list(attributes.get('Reactants'))], [str(s) for s in as_list(attributes.get('Products'))]
        models = []
        for model in as_list(attributes.get('ChemistryModel')):
            columns = [str(value) for value in model] if isinstance(model, (list, tuple)) else [str(model)]
            models.append((columns[0], columns[1] if len(columns) > 1 else None))
        value = attributes.get('ReactionModel')
        kind = str(value) if isinstance(value, str) else str((as_list(value) or ['TCE'])[0])
        spec = ReactionSpec(name=name, reactants=reactants, products=products, models=models, model=kind)
        if kind == 'TCE':
            C, n, Td = (as_float(attributes.get(key)) for key in ('Arrhenius-Prefactor', 'Arrhenius-Powerfactor', 'Activation-Energy_K'))
            key, explicit = canonical(reactants, products)
            found = [(table, row) for table in tables for row in table.rows if row.key == key and not same(row, table.unit, C, n, Td)]
            own_paper = [(table, row) for table, row in found if table.chemistry_model and any(model.endswith('_' + table.chemistry_model) for model, _ in models)]
            if own_paper or found:
                table, row = min(own_paper or found, key=lambda item: abs(item[1].prefactor(item[0].unit) / C - 1.0))  # the closest C
                spec.rates, spec.row = Requirement.parse(table.name), row.row
                if row.third_bodies:
                    bodies = [b for _, listed in models for b in (listed or '').split(',') if b]
                    spec.third_body = explicit if explicit in row.third_bodies else next((b for b in bodies if b in row.third_bodies), row.third_bodies[0])
                if not own_paper:
                    notes.append(f'{name}: values from {table.name} row {row.row}, not from the paper of its chemistry models')
            else:
                spec.arrhenius = {'C': C, 'n': n, 'Td': Td}
                spec.reference = 'source unknown (in no rate table of the store)'
        specs[name] = spec
    references = as_list(database.attributes.get('Reactions@AvailableChemistryModels,Reference'))
    models_references = {str(item[0]): str(item[1]) for item in references if isinstance(item, (list, tuple)) and len(item) > 1}
    return specs, models_references, notes


def spec_yaml(spec: ReactionSpec) -> dict[str, object]:
    """Recipe entry of a reaction (inverse of parse_reaction_spec)"""
    data: dict[str, object] = {'reactants': spec.reactants, 'products': spec.products}
    if spec.model != 'TCE':
        data['model'] = spec.model
    if spec.rates is not None:
        data['rates'] = str(spec.rates)
    for key in ('row', 'third_body', 'arrhenius', 'reference'):
        if getattr(spec, key) is not None:
            data[key] = getattr(spec, key)
    data['models'] = dict(spec.models)
    return data


# ----------------------------------------------------------------------------------------------------------------------------------
# Preview of a rate table before it is stored (literature add -n), optionally compared with a database
# ----------------------------------------------------------------------------------------------------------------------------------
def database_matches(database: Database, row: RateRow, unit: str) -> tuple[list[str], Optional[tuple[str, list[str]]]]:
    """Reactions of a database with the same reactants and products and the same C, n and T_d as a table row; else the closest one
    (by C) with its differences"""
    same_values: list[str] = []
    closest: Optional[tuple[float, str, list[str]]] = None
    for name, reaction in database.reactions.items():
        attributes = reaction.attributes
        if 'Arrhenius-Prefactor' not in attributes:
            continue
        key, _ = canonical([str(s) for s in as_list(attributes.get('Reactants'))], [str(s) for s in as_list(attributes.get('Products'))])
        if key != row.key:
            continue
        C, n, Td = (as_float(attributes.get(item)) for item in ('Arrhenius-Prefactor', 'Arrhenius-Powerfactor', 'Activation-Energy_K'))
        differences = same(row, unit, C, n, Td)
        if not differences:
            same_values.append(name)
        else:
            distance = abs(math.log(C / row.prefactor(unit))) if C > 0 else math.inf
            if closest is None or distance < closest[0]:
                closest = (distance, name, differences)
    return same_values, (closest[1], closest[2]) if closest and not same_values else None


def preview(rows: list[RateRow], unit: str, database: Optional[Database] = None) -> tuple[list[str], list[list[str]], dict[str, int]]:
    """Header and lines of the rows as understood (reaction, third bodies, C converted to PICLas units, n, T_d, Tx) and, with a
    database, the reactions with the same values or the closest one; counts of rows found, differing and not in the database"""
    header = ['Row', 'Reaction', 'Third body', 'C (PICLas)', 'n', 'T_d', 'Tx']
    counts = {'same': 0, 'differs': 0, 'absent': 0}
    lines = []
    for row in rows:
        line = [row.row, str(row.key), ', '.join(row.third_bodies), f'{row.prefactor(unit):.4g}', f'{row.n:g}', f'{row.Td:g}', row.Tx]
        if database is not None:
            found, closest = database_matches(database, row, unit)
            if found:
                line.append('= ' + ', '.join(found))
                counts['same'] += 1
            elif closest:
                line.append(f'≠ {closest[0]}: ' + '; '.join(closest[1]))
                counts['differs'] += 1
            else:
                line.append('–')
                counts['absent'] += 1
        lines.append(line)
    if database is not None:
        header.append('In the database (= same values, ≠ closest, – no such reaction)')
    return header, lines, counts
