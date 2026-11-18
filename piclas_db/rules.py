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
"""Check rules for the content of a database, derived from the problems found in existing databases

Every rule works on the layout-independent data model and returns findings with a severity:
ERROR   PICLas computes something wrong, ignores data or aborts
WARNING inconsistent or risky data
INFO    cosmetic, or a remark on how PICLas treats the data
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import difflib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import Enum, unique
from typing import Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import numpy as np

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.model import XSEC_DATASET_KINDS, XSEC_GROUP_KINDS, XSEC_THRESHOLD_KINDS, CollisionPair, CrossSection, Database, Species, XSecKind
from piclas_db.reference import (
    CM_TO_K,
    DUMMY_LEVEL_K,
    EV_TO_K,
    FULLY_IONIZED,
    GROUND_STATE_DEGENERACY,
    IONIZATION_ENERGY_EV,
    SPECIES_ATTRIBUTES,
    SPECIES_REQUIRED_ATTRIBUTES,
)
from piclas_db import provenance
from piclas_db.schema import Schema
# ==================================================================================================================================

ELEMENTARY_CHARGE = 1.602176634e-19  # C
SIGMA_MAX_M2 = 1.0e-16  # larger cross-sections are most likely given in cm^2
KIND_NAMES = [kind.value for kind in XSEC_DATASET_KINDS + XSEC_GROUP_KINDS]


@unique
class Severity(Enum):
    ERROR = 'ERROR'
    WARNING = 'WARNING'
    INFO = 'INFO'


SEVERITY_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}


@dataclass(frozen=True)
class Finding:
    severity: Severity
    rule: str  # rule identifier, e.g. 'levels-ground-state'
    path: str  # location in the file, e.g. '/Species/ArIon1/ElectronicLevel'
    message: str

    def as_dict(self) -> dict[str, str]:
        return {'severity': self.severity.value, 'rule': self.rule, 'path': self.path, 'message': self.message}


Rule = Callable[[Database], Iterator[Finding]]


def suggestion(name: str, candidates: list[str]) -> Optional[str]:
    """Closest known name for a probable typo"""
    matches = difflib.get_close_matches(name, candidates, n=1, cutoff=0.6)
    return matches[0] if matches else None


# ----------------------------------------------------------------------------------------------------------------------------------
# Species
# ----------------------------------------------------------------------------------------------------------------------------------
def species_path(database: Database, species: Species) -> str:
    return f'/{species.name}' if database.schema is Schema.LEGACY_ELECTRONIC else f'/Species/{species.name}'


def level_path(database: Database, species: Species) -> str:
    return species_path(database, species) + ('' if database.schema is Schema.LEGACY_ELECTRONIC else '/ElectronicLevel')


def check_species_attributes(database: Database) -> Iterator[Finding]:
    if database.schema is not Schema.SPECIES_DATABASE:
        return
    for species in database.species.values():
        path = species_path(database, species)
        for name in species.attributes:
            if name in SPECIES_ATTRIBUTES:
                continue
            known = suggestion(name, list(SPECIES_ATTRIBUTES))
            if known:
                yield Finding(Severity.ERROR, 'species-attribute-unknown', path, f"attribute '{name}' is not read by PICLas (did you mean '{known}'?)")
            else:
                yield Finding(Severity.WARNING, 'species-attribute-unknown', path, f"attribute '{name}' is not read by PICLas")
        for name in SPECIES_REQUIRED_ATTRIBUTES:
            if name not in species.attributes:
                yield Finding(Severity.ERROR, 'species-attribute-missing', path, f"required attribute '{name}' is missing")
        interaction = species.attributes.get('InteractionID')
        if interaction is not None and not isinstance(interaction, int):
            yield Finding(Severity.INFO, 'species-attribute-type', path, 'InteractionID is stored as float instead of integer')


def check_electronic_levels(database: Database) -> Iterator[Finding]:
    for species in database.species.values():
        path = level_path(database, species)
        if species.electronic_placeholder:
            if species.name == 'electron' or species.name in FULLY_IONIZED:
                continue
            yield Finding(Severity.WARNING, 'levels-placeholder', path, 'placeholder instead of electronic levels')
            continue
        levels = species.electronic_levels
        if levels is None:
            continue
        if species.dtypes.get('ElectronicLevel', 'float64') == 'float32':
            yield Finding(Severity.WARNING, 'data-float32', path, 'stored as float32')

        dummy = levels[:, 1] >= DUMMY_LEVEL_K
        if dummy.any():
            yield Finding(Severity.INFO, 'levels-dummy', path, f'{int(dummy.sum())} dummy level(s) above {DUMMY_LEVEL_K:.0e} K')
        real = levels[~dummy]
        degeneracy, energy = real[:, 0], real[:, 1]

        if not np.all(np.isfinite(real)) or np.any(energy < 0.0):
            yield Finding(Severity.ERROR, 'levels-values', path, 'negative or non-finite energies')
            continue
        if np.any(degeneracy < 1.0) or np.any(degeneracy != np.round(degeneracy)):
            yield Finding(Severity.ERROR, 'levels-degeneracy', path, 'degeneracies must be positive integers')

        ground = int(np.argmin(energy))
        if energy[ground] > 0.0:
            yield Finding(Severity.ERROR, 'levels-ground-state', path, f'lowest level at {energy[ground]:.6g} K instead of 0 K (ground state missing?)')
        elif species.name in GROUND_STATE_DEGENERACY and degeneracy[ground] != GROUND_STATE_DEGENERACY[species.name]:
            yield Finding(
                Severity.ERROR,
                'levels-ground-state',
                path,
                f'ground state degeneracy {degeneracy[ground]:g} instead of {GROUND_STATE_DEGENERACY[species.name]} (NIST ASD)',
            )

        if np.any(np.diff(energy) < 0.0):
            yield Finding(Severity.INFO, 'levels-unsorted', path, f'levels not sorted by energy ({int(np.sum(np.diff(energy) < 0.0))} decreasing steps); PICLas sorts them after reading')
        duplicates = len(energy) - len(np.unique(energy))
        if duplicates:
            yield Finding(Severity.INFO, 'levels-duplicate', path, f'{duplicates} level(s) with the same energy as another level')

        if species.name in IONIZATION_ENERGY_EV and len(energy) > 1:
            limit = IONIZATION_ENERGY_EV[species.name] * EV_TO_K
            highest = float(np.max(energy))
            if abs(highest * CM_TO_K - limit) / limit < 0.005:
                yield Finding(
                    Severity.ERROR,
                    'levels-unit',
                    path,
                    f'energies appear to be in cm^-1 instead of K: highest level {highest:.6g} x {CM_TO_K} = ionization energy; all levels {CM_TO_K}x too low',
                )
            elif highest > 1.001 * limit:
                yield Finding(Severity.WARNING, 'levels-above-ionization', path, f'highest level {highest:.6g} K above the ionization energy {limit:.6g} K')


# ----------------------------------------------------------------------------------------------------------------------------------
# Reactions
# ----------------------------------------------------------------------------------------------------------------------------------
def numeric_attribute(database: Database, names: list[str], attribute: str, default: Optional[float]) -> Optional[dict[str, float]]:
    """Numeric attribute of the given species, None if it is missing or not a number for any of them"""
    values: dict[str, float] = {}
    for name in names:
        value = database.species[name].attributes.get(attribute, default)
        if not isinstance(value, (int, float)):
            return None
        values[name] = float(value)
    return values


def check_reactions(database: Database) -> Iterator[Finding]:
    mass_deviations: dict[str, float] = {}
    for reaction in database.reactions.values():
        path = f'/Reactions/{reaction.name}'
        for name in ('Reactants', 'Products', 'ReactionModel', 'ChemistryModel'):
            if name not in reaction.attributes:
                yield Finding(Severity.ERROR, 'reaction-attribute-missing', path, f"required attribute '{name}' is missing")
        model = reaction.attributes.get('ReactionModel')
        model_name = model[0] if isinstance(model, list) and model else model
        if model_name == 'TCE':
            for name in ('Arrhenius-Prefactor', 'Arrhenius-Powerfactor', 'Activation-Energy_K'):
                if name not in reaction.attributes:
                    yield Finding(Severity.ERROR, 'reaction-attribute-missing', path, f"attribute '{name}' is required for TCE")

        names = reaction.reactants + reaction.products
        missing = sorted({name for name in names if name not in database.species})
        if missing:
            yield Finding(Severity.ERROR, 'reaction-species-missing', path, f'species not in /Species: {", ".join(missing)}')
            continue
        masses = numeric_attribute(database, names, 'MassIC', None)
        if masses is None:
            continue
        mass_in = sum(masses[name] for name in reaction.reactants)
        mass_out = sum(masses[name] for name in reaction.products)
        if mass_in > 0.0 and abs(mass_in - mass_out) / mass_in > 1.0e-6:
            mass_deviations[reaction.name] = abs(mass_in - mass_out) / mass_in
        charges = numeric_attribute(database, names, 'ChargeIC', 0.0)
        if charges is not None:
            charge_in = sum(charges[name] for name in reaction.reactants)
            charge_out = sum(charges[name] for name in reaction.products)
            if abs(charge_in - charge_out) > 1.0e-3 * ELEMENTARY_CHARGE:
                yield Finding(Severity.ERROR, 'reaction-charge', path, 'charge not conserved')

    if mass_deviations:
        # Species occurring in all reactions with a mass deviation are the most likely cause
        involved: dict[str, int] = {}
        for name in mass_deviations:
            reaction = database.reactions[name]
            for species in set(reaction.reactants + reaction.products):
                involved[species] = involved.get(species, 0) + 1
        suspects = sorted(involved, key=lambda species: -involved[species])[:3]
        yield Finding(
            Severity.WARNING,
            'reaction-mass',
            '/Reactions',
            f'{len(mass_deviations)} reactions do not conserve mass (relative deviation up to {max(mass_deviations.values()):.1e}); MassIC inconsistent, most frequent species: {", ".join(suspects)}',
        )


# ----------------------------------------------------------------------------------------------------------------------------------
# Cross-sections
# ----------------------------------------------------------------------------------------------------------------------------------
def pair_path(database: Database, pair: CollisionPair) -> str:
    return f'/{pair.name}' if database.schema is Schema.LEGACY_XSEC else f'/Cross-Sections/{pair.name}'


def xsec_path(database: Database, pair: CollisionPair, xsec: CrossSection) -> str:
    return pair_path(database, pair) + (f'/{xsec.group}' if xsec.group else '') + f'/{xsec.key}'


def significant_digits_at_most(values: np.ndarray, digits: int) -> bool:
    """True if all non-zero values are representable with the given number of significant digits (float32 tolerant)"""
    values = values[np.abs(values) > 0.0]
    if values.size == 0:
        return False
    exponent = np.floor(np.log10(np.abs(values)))
    scaled = values / 10.0 ** (exponent - digits + 1)
    return bool(np.allclose(scaled, np.round(scaled), rtol=0.0, atol=1.0e-4))


def process_text(xsec: CrossSection) -> str:
    return ' '.join(str(text) for text in (xsec.provenance.info, xsec.provenance.extra.get('PROCESS')) if text)


def check_cross_section_data(database: Database, pair: CollisionPair, xsec: CrossSection) -> Iterator[Finding]:
    path = xsec_path(database, pair, xsec)
    data = xsec.data
    minimum_points = 1 if xsec.kind is XSecKind.SPECTRUM else 2  # a spectrum can be a single photon energy
    if data.ndim != 2 or data.shape[1] != 2 or data.shape[0] < minimum_points:
        yield Finding(Severity.ERROR, 'xsec-shape', path, f'shape {data.shape} instead of (n_rows, 2) with n_rows >= {minimum_points}')
        return
    energy, sigma = data[:, 0], data[:, 1]
    if not np.all(np.isfinite(data)) or np.any(energy < 0.0) or np.any(sigma < 0.0):
        yield Finding(Severity.ERROR, 'xsec-values', path, 'negative or non-finite values')
        return

    steps = np.diff(energy)
    if np.any(steps < 0.0):
        yield Finding(Severity.ERROR, 'xsec-energy-order', path, 'energies not increasing')
    flat = (steps >= 0.0) & (steps <= 0.0)  # exactly equal neighbouring energies
    duplicates = int(np.sum(flat))
    if duplicates >= 3:
        yield Finding(Severity.ERROR, 'xsec-energy-duplicate', path, f'{duplicates} duplicate energy points (energies rounded?)')
    elif duplicates:
        first = float(energy[1:][flat][0])
        yield Finding(Severity.WARNING, 'xsec-energy-duplicate', path, f'duplicate energy point at {first:g} eV (interpolation ambiguous)')
    if xsec.kind is not XSecKind.SPECTRUM and float(np.max(sigma)) > SIGMA_MAX_M2:
        yield Finding(Severity.WARNING, 'xsec-magnitude', path, f'cross-section up to {float(np.max(sigma)):.2e} m^2 (given in cm^2?)')

    if xsec.kind is XSecKind.REACTION and sigma[0] > 0.0:
        yield Finding(
            Severity.WARNING,
            'xsec-reaction-threshold',
            path,
            f'first data point at {energy[0]:g} eV with cross-section > 0: PICLas prepends zero at the heat of reaction (threshold region interpolated)',
        )


def check_cross_section_names(database: Database, pair: CollisionPair, xsec: CrossSection) -> Iterator[Finding]:
    path = xsec_path(database, pair, xsec)
    if xsec.kind is XSecKind.UNDEFINED:
        yield Finding(Severity.WARNING, 'xsec-undefined', path, 'excitation not assigned to rotation, vibration or electronic (ignored by PICLas)')
    if xsec.kind in XSEC_THRESHOLD_KINDS:
        try:
            threshold = float(xsec.key)
        except ValueError:
            yield Finding(Severity.ERROR, 'xsec-threshold-name', path, f"dataset name '{xsec.key}' is not a number (PICLas reads the threshold from the name)")
            return
        if xsec.threshold is not None and abs(xsec.threshold - threshold) > 1.0e-3 * max(abs(threshold), 1.0):
            yield Finding(Severity.WARNING, 'xsec-threshold-mismatch', path, f'threshold {xsec.threshold:g} eV in the attributes differs from the name')
    if xsec.kind is XSecKind.REACTION and database.schema is Schema.SPECIES_DATABASE and database.species:
        missing = sorted({name for name in xsec.key.split('-') if name not in database.species})
        if missing:
            yield Finding(Severity.WARNING, 'xsec-products-missing', path, f'product(s) {", ".join(missing)} not in /Species: the reaction cannot be used')
    if xsec.kind is XSecKind.REACTION:
        products = xsec.key.split('-')
        heavy = [name for name in products if name != 'electron']
        if products != heavy + ['electron'] * (len(products) - len(heavy)):
            yield Finding(
                Severity.WARNING,
                'xsec-product-order',
                path,
                f"product order '{xsec.key}' differs from the convention (heavy species first); it must match the reaction in parameter.ini",
            )


def check_collision_pair(database: Database, pair: CollisionPair) -> Iterator[Finding]:
    path = pair_path(database, pair)
    first, _, second = pair.name.partition('-')
    if f'{second}-{first}' in database.collision_pairs and first < second:
        yield Finding(Severity.ERROR, 'xsec-pair-duplicate', path, f'pair also stored as {second}-{first}; PICLas reads only one of them')

    for xsec in pair.cross_sections:
        yield from check_cross_section_names(database, pair, xsec)
        yield from check_cross_section_data(database, pair, xsec)

    # Unknown group or dataset names (e.g. typos), one finding per name
    unknown: dict[str, int] = {}
    for xsec in pair.of_kind(XSecKind.UNKNOWN):
        name = xsec.group or xsec.key
        unknown[name] = unknown.get(name, 0) + 1
    for name, count in unknown.items():
        known = suggestion(name, KIND_NAMES)
        datasets = f' ({count} datasets)' if count > 1 else ''
        if known:
            yield Finding(Severity.ERROR, 'xsec-name-unknown', f'{path}/{name}', f"'{name}'{datasets} is ignored by PICLas (did you mean '{known}'?)")
        else:
            yield Finding(Severity.WARNING, 'xsec-name-unknown', f'{path}/{name}', f"'{name}'{datasets} is not read by PICLas")

    rounded = [xsec for xsec in pair.cross_sections if xsec.data.ndim == 2 and len(xsec.data) >= 10 and significant_digits_at_most(xsec.data[:, 1], 3)]
    if rounded:
        yield Finding(
            Severity.INFO,
            'xsec-rounded',
            path,
            f'{len(rounded)} of {len(pair.cross_sections)} cross-sections given with at most 3 significant digits (compare with the original source)',
        )
    float32 = [xsec for xsec in pair.cross_sections if xsec.dtype == 'float32']
    if float32:
        yield Finding(Severity.WARNING, 'data-float32', path, f'{len(float32)} of {len(pair.cross_sections)} cross-sections stored as float32')
    for group in pair.empty_groups:
        yield Finding(Severity.INFO, 'xsec-empty-group', f'{path}/{group}', 'empty group')

    # Thresholds that are equal as numbers but differ as names (e.g. '14' and '14.0')
    for group in {xsec.group for xsec in pair.cross_sections if xsec.group}:
        thresholds: dict[float, list[str]] = {}
        for xsec in pair.cross_sections:
            if xsec.group == group and xsec.kind in XSEC_THRESHOLD_KINDS + (XSecKind.UNKNOWN,):
                try:
                    thresholds.setdefault(float(xsec.key), []).append(xsec.key)
                except ValueError:
                    continue
        for value, names in thresholds.items():
            if len(names) > 1:
                yield Finding(Severity.WARNING, 'xsec-threshold-duplicate', f'{path}/{group}', f'datasets {", ".join(names)} have the same threshold {value:g} eV')

    # Reactions with the same products in a different order: the order is the only thing that distinguishes the channels
    channels: dict[tuple[str, ...], list[str]] = {}
    for xsec in pair.of_kind(XSecKind.REACTION):
        channels.setdefault(tuple(sorted(xsec.key.split('-'))), []).append(xsec.key)
    for names in channels.values():
        if len(names) > 1:
            yield Finding(Severity.ERROR, 'xsec-reaction-ambiguous', f'{path}/REACTION', f'{" and ".join(names)} have the same products; only the order distinguishes the channels')

    # Dissociative excitation stored as excitation while dissociation reactions exist
    if pair.of_kind(XSecKind.REACTION):
        for xsec in pair.of_kind(XSecKind.ELECTRONIC):
            if 'DISOC' in process_text(xsec).upper() or 'DISS' in process_text(xsec).upper():
                yield Finding(
                    Severity.WARNING,
                    'xsec-double-counting',
                    xsec_path(database, pair, xsec),
                    'dissociative excitation stored as electronic excitation while the pair also has reactions (double counting?)',
                )


def check_cross_sections(database: Database) -> Iterator[Finding]:
    for pair in database.collision_pairs.values():
        yield from check_collision_pair(database, pair)


# ----------------------------------------------------------------------------------------------------------------------------------
# Provenance
# ----------------------------------------------------------------------------------------------------------------------------------
def check_provenance(database: Database) -> Iterator[Finding]:
    undocumented = [species.name for species in database.species.values() if species.provenance.is_empty and (species.electronic_levels is not None or species.attributes)]
    if len(undocumented) == 1:
        yield Finding(Severity.WARNING, 'provenance-missing', species_path(database, database.species[undocumented[0]]), 'no reference')
    elif undocumented:
        root = '/' if database.schema is Schema.LEGACY_ELECTRONIC else '/Species'
        yield Finding(Severity.WARNING, 'provenance-missing', root, f'{len(undocumented)} of {len(database.species)} species without reference')
    for pair in database.collision_pairs.values():
        undocumented = [xsec for xsec in pair.cross_sections if xsec.provenance.reference is None and xsec.provenance.info is None and pair.provenance.reference is None]
        if undocumented:
            yield Finding(Severity.WARNING, 'provenance-missing', pair_path(database, pair), f'{len(undocumented)} of {len(pair.cross_sections)} cross-sections without reference or info')
        for xsec in pair.cross_sections:
            path = xsec_path(database, pair, xsec)
            if 'source_csv' in xsec.provenance.extra:
                yield Finding(Severity.INFO, 'provenance-converter', path, 'written by a generic CSV converter (columns, num_rows, source_csv)')
            if any(isinstance(value, list) and value and isinstance(value[0], list) for value in xsec.provenance.extra.values()):
                yield Finding(Severity.INFO, 'provenance-2d-strings', path, 'string attributes stored as 2D arrays')


def check_file_provenance(database: Database) -> Iterator[Finding]:
    """Root attributes written by piclas-db: how the file was made"""
    record = provenance.read(database.attributes)
    if not record.present:
        if database.schema is Schema.SPECIES_DATABASE:
            yield Finding(Severity.INFO, 'provenance-file', '/', 'not written by piclas-db: origin of the file unknown (rebuild derives a recipe)')
        return
    if record.format_version is not None and record.format_version > provenance.FORMAT_VERSION:
        yield Finding(
            Severity.WARNING,
            'provenance-format',
            '/',
            f'written by piclas-db {record.version} with layout version {record.format_version}; this version knows up to {provenance.FORMAT_VERSION}',
        )
    if record.recipe is not None and not record.recipe_intact:
        yield Finding(Severity.WARNING, 'provenance-recipe', '/', 'embedded recipe does not match its sha256 (modified after the build)')


def check_literature_review(database: Database) -> Iterator[Finding]:
    """Cross-sections from papers whose extraction has not been reviewed"""
    for pair in database.collision_pairs.values():
        for xsec in pair.cross_sections:
            status = str(xsec.provenance.extra.get('* Review', ''))
            if status and not status.startswith('approved'):
                path = f'/Cross-Sections/{pair.name}/' + (f'{xsec.group}/' if xsec.group else '') + xsec.key
                yield Finding(Severity.WARNING, 'literature-unreviewed', path, f'data from a paper, extraction {status.split(" ", maxsplit=1)[0]}')


RULES: tuple[Rule, ...] = (check_file_provenance, check_literature_review, check_species_attributes, check_electronic_levels, check_reactions, check_cross_sections, check_provenance)


def run_checks(database: Database) -> list[Finding]:
    """All findings for a database, sorted by severity and path"""
    findings = [finding for rule in RULES for finding in rule(database)]
    findings.extend(Finding(Severity.ERROR, 'file-unreadable', path, 'dataset cannot be read') for path in database.unreadable)
    if database.schema is Schema.UNKNOWN:
        findings.append(Finding(Severity.ERROR, 'file-layout', '/', 'unknown layout'))
    return sorted(findings, key=lambda finding: (SEVERITY_ORDER[finding.severity], finding.path, finding.rule))
