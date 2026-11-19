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
"""ATcT IDs for the species of an existing database (piclas-db atct map): the formula and charge follow from the PICLas name (CO2,
ArIon1, CIon6), ATcT is searched by formula and name, gas-phase records with the same composition and charge are candidates, and the
heat of formation stored in the file decides between them (states and isomers differ by far more than TN versions do).

    Ar      -> composition {Ar: 1}, charge 0, queries 'Ar', 'argon'
    ArIon1  -> composition {Ar: 1}, charge 1, queries 'Ar+', 'Ar', 'argon cation'
    CIon6   -> composition {C: 1},  charge 6, queries '[C]+6', 'C'

Only species whose reference credits ATcT are mapped (the others have no ATcT value to check against).
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import yaml

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.model import Database, Species
from piclas_db.sources.atct import GAS_CONSTANT, ATcTSpecies
from piclas_db.sources.own import credits_atct, split_reference
# ==================================================================================================================================

ELEMENT_NAMES = {'H': 'hydrogen', 'He': 'helium', 'C': 'carbon', 'N': 'nitrogen', 'O': 'oxygen', 'F': 'fluorine', 'Ne': 'neon',
                 'Ar': 'argon', 'Kr': 'krypton', 'Xe': 'xenon', 'Fe': 'iron', 'Cl': 'chlorine', 'S': 'sulfur', 'Si': 'silicon'}  # fmt: skip
MOLECULE_NAMES = {'C2': 'dicarbon', 'CH': 'methylidyne', 'CH2': 'methylene', 'CH3': 'methyl', 'CH4': 'methane', 'CN': 'cyano',
                  'CO': 'carbon monoxide', 'CO2': 'carbon dioxide', 'H2': 'dihydrogen', 'H3': 'trihydrogen', 'HCN': 'hydrogen cyanide',
                  'N2': 'dinitrogen', 'NH': 'imidogen', 'NO': 'nitric oxide', 'O2': 'dioxygen', 'H2O': 'water'}  # fmt: skip
ION_NAMES = {1: 'cation', 2: 'dication', 3: 'trication'}
TOLERANCE = 1.0  # kJ/mol: accepted difference of the heat of formation between the file (TN 1.130) and the current TN version


class Status(Enum):
    MATCH = 'match'  # one candidate within the tolerance (or one clearly closest)
    CHECK = 'check'  # candidates, but none (or several) within the tolerance: decide by hand
    NOT_FOUND = 'not found'  # no gas-phase record with this composition and charge
    UNKNOWN_NAME = 'name not understood'


Composition = dict[str, int]


def composition(formula: str) -> Optional[Composition]:
    """Element counts of a formula such as CO2, HCN, CH3, C(O)OH; None if it cannot be read"""
    counts: Composition = {}
    stack: list[Composition] = [counts]
    for token in re.findall(r'[A-Z][a-z]?\d*|[()]\d*|.', formula.replace(' ', '')):
        if token.startswith('('):
            stack.append({})
        elif token.startswith(')'):
            if len(stack) == 1:
                return None
            group, factor = stack.pop(), int(token[1:] or 1)
            for element, count in group.items():
                stack[-1][element] = stack[-1].get(element, 0) + count * factor
        elif (atom := re.fullmatch(r'([A-Z][a-z]?)(\d*)', token)) is not None:
            stack[-1][atom.group(1)] = stack[-1].get(atom.group(1), 0) + int(atom.group(2) or 1)
        else:
            return None
    return counts if len(stack) == 1 and counts else None


def piclas_name(name: str) -> Optional[tuple[str, Composition, int]]:
    """Formula, composition and charge of a PICLas species name: CO2 -> ('CO2', {C: 1, O: 2}, 0), ArIon1 -> ('Ar', {Ar: 1}, 1)"""
    match = re.fullmatch(r'(?P<base>.+?)(Ion(?P<charge>\d+))?', name)
    if match is None:
        return None
    base = match.group('base')
    counts = composition(base)
    return None if counts is None else (base, counts, int(match.group('charge') or 0))


def atct_formula(formula: str) -> Optional[tuple[Composition, int]]:
    """Composition and charge of an ATcT formula: 'CO (g)', 'Ar+ (g)', '[Ar]+2 (g)', '[ArH]+ (g)', 'OH- (g)'"""
    text = re.split(r'\s*\((?:g|aq|cr|l)\b', formula, maxsplit=1)[0].strip()  # without the phase
    match = re.fullmatch(r'\[?(?P<body>[^\]]+?)\]?(?P<sign>[+-])(?P<number>\d*)', text)
    if match is None:
        counts = composition(text)
        return None if counts is None else (counts, 0)
    counts = composition(match.group('body'))
    charge = int(match.group('number') or 1) * (1 if match.group('sign') == '+' else -1)
    return None if counts is None else (counts, charge)


def queries(base: str, counts: Composition, charge: int) -> list[str]:
    """Search terms for ATcT, most specific first"""
    terms = [f'{base}+' if charge == 1 else f'[{base}]+{charge}'] if charge > 0 else []
    terms.append(base)
    name = ELEMENT_NAMES.get(base) if len(counts) == 1 and sum(counts.values()) == 1 else MOLECULE_NAMES.get(base)
    if name and (charge == 0 or charge in ION_NAMES):
        terms.append(f'{name} {ION_NAMES[charge]}' if charge else name)  # the formula search can miss records among many similar ones
    return [term for term in dict.fromkeys(terms) if term]


@dataclass
class Candidate:
    record: ATcTSpecies
    deviation: Optional[float]  # kJ/mol: ATcT dfH(298 K) - value of the file (HeatOfFormation_K * R)
    mass_deviation: Optional[float]  # relative: (mass of the file - ATcT mass) / ATcT mass


@dataclass
class Mapping:
    species: str
    status: Status
    candidates: list[Candidate] = field(default_factory=list)  # closest first
    queries: list[str] = field(default_factory=list)

    @property
    def chosen(self) -> Optional[Candidate]:
        return self.candidates[0] if self.status is Status.MATCH else None


def candidates_for(species: Species, records: list[ATcTSpecies], counts: Composition, charge: int) -> list[Candidate]:
    """Gas-phase records with the composition and charge of the species, closest heat of formation first"""
    heat = species.attributes.get('HeatOfFormation_K')
    mass = species.attributes.get('MassIC')
    found: list[Candidate] = []
    for record in records:
        parts = atct_formula(record.formula)
        if not record.gas or parts is None or parts != (counts, charge) or record.charge != charge:
            continue
        deviation = record.hf_298k - float(heat) * GAS_CONSTANT if record.hf_298k is not None and isinstance(heat, (int, float)) else None  # ty: ignore[invalid-argument-type]
        mass_deviation = (float(mass) - record.mass_kg) / record.mass_kg if record.mass_kg and isinstance(mass, (int, float)) else None  # ty: ignore[invalid-argument-type]
        found.append(Candidate(record, deviation, mass_deviation))
    return sorted(found, key=lambda candidate: (candidate.deviation is None, abs(candidate.deviation or 0.0), candidate.record.atct_id))


def decide(candidates: list[Candidate], tolerance: float) -> Status:
    """MATCH: exactly one candidate within the tolerance, or the closest within it and all others more than ten times further away"""
    within = [candidate for candidate in candidates if candidate.deviation is not None and abs(candidate.deviation) <= tolerance]
    if not candidates:
        return Status.NOT_FOUND
    if len(within) == 1:
        return Status.MATCH
    if within and all(abs(other.deviation or 0.0) > 10.0 * max(abs(within[0].deviation or 0.0), 1.0e-3) for other in within[1:]):
        return Status.MATCH
    return Status.CHECK


def atct_species(database: Database) -> list[str]:
    """Species whose reference credits ATcT"""
    return [name for name, species in sorted(database.species.items()) if credits_atct(split_reference(species.provenance, species.attributes)[0])]


def map_species(database: Database, names: list[str], search: Callable[[str], list[ATcTSpecies]], tolerance: float = TOLERANCE) -> list[Mapping]:
    """ATcT candidates for each species; search(term) is called once per term (cached)"""
    cache: dict[str, list[ATcTSpecies]] = {}
    mappings = []
    for name in names:
        parsed = piclas_name(name)
        if parsed is None:
            mappings.append(Mapping(name, Status.UNKNOWN_NAME))
            continue
        base, counts, charge = parsed
        terms = queries(base, counts, charge)
        records: dict[str, ATcTSpecies] = {}
        for term in terms:
            if term not in cache:
                cache[term] = search(term)
            records.update({record.atct_id: record for record in cache[term]})
        candidates = candidates_for(database.species[name], list(records.values()), counts, charge)
        mappings.append(Mapping(name, decide(candidates, tolerance), candidates, terms))
    return mappings


def describe(candidate: Candidate) -> str:
    record = candidate.record
    deviation = '' if candidate.deviation is None else f', dfH {candidate.deviation:+.3f} kJ/mol vs. file'
    mass = '' if candidate.mass_deviation is None else f', mass of the file {candidate.mass_deviation:+.1e}'
    return f'{record.atct_id} {record.formula} TN {record.version}{deviation}{mass}'


def recipe_text(mappings: list[Mapping], source: str, own_data: Optional[str]) -> str:
    """Recipe entries: matched species with their ATcT ID, the others as comments with the closest candidates"""
    lines = [f'# ATcT IDs for the species of {source} (piclas-db atct map): check every entry before use', '']
    if own_data:
        lines += [f'own_data: {own_data}']
    lines += ['species:']
    for mapping in mappings:
        if mapping.chosen is not None:
            key = yaml.safe_dump(mapping.species).splitlines()[0]  # quoted where YAML would read something else (e.g. 'NO')
            lines.append(f'  {key}: {{atct: {mapping.chosen.record.atct_id}}}  # {describe(mapping.chosen)}')
        else:
            lines.append(f'  # {mapping.species}: {mapping.status.value} (searched: {", ".join(mapping.queries) or "-"})')
            lines += [f'  #   candidate {describe(candidate)}' for candidate in mapping.candidates[:3]]
    return '\n'.join(lines) + '\n'
