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
"""Comparison of two databases of any layout ('piclas-db diff')

Entries are matched in the current layout: species by name, cross-sections by collision pair (A-B equals B-A), kind and key, where
thresholds are compared as numbers and reaction products independently of their order. Every matched entry is classified as
identical, numerically different (with the size and energy range of the deviation), different in its attributes or only present in
one file. Data that differ and also have different references are marked as coming from different sources.
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import difflib
from dataclasses import dataclass, field
from enum import Enum, unique
from typing import Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import numpy as np

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.model import XSEC_DATASET_KINDS, XSEC_GROUP_KINDS, XSEC_THRESHOLD_KINDS, AttrValue, CrossSection, Database, Provenance, Species, XSecKind
# ==================================================================================================================================

DEFAULT_RTOL = 1.0e-6  # relative tolerance for 'identical'; covers float32 storage (about 6e-8)
KIND_NAMES = [kind.value for kind in XSEC_DATASET_KINDS + XSEC_GROUP_KINDS]


@unique
class Change(Enum):
    ONLY_IN_A = 'only in A'
    ONLY_IN_B = 'only in B'
    NUMERIC = 'numerically different'
    SCALED = 'scaled'
    STRUCTURE = 'different structure'
    ATTRIBUTE = 'attributes differ'
    RENAMED = 'renamed'


@dataclass(frozen=True)
class Difference:
    change: Change
    path: str  # path in the current layout
    message: str
    different_source: bool = False

    def as_dict(self) -> dict[str, object]:
        return {'change': self.change.value, 'path': self.path, 'message': self.message, 'different_source': self.different_source}


@dataclass
class Comparison:
    a: str
    b: str
    differences: list[Difference] = field(default_factory=list)
    identical: int = 0  # number of matched entries without any difference
    compared: list[str] = field(default_factory=list)  # categories compared
    skipped: list[str] = field(default_factory=list)  # categories present in only one file and not compared

    @property
    def equal(self) -> bool:
        return not self.differences


# ----------------------------------------------------------------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------------------------------------------------------------
def different_source(a: Provenance, b: Provenance) -> bool:
    """True if both entries carry a reference and the references name different sources (retrieval dates are ignored)"""
    if a.reference is None or b.reference is None:
        return False
    return source_name(a.reference) != source_name(b.reference)


def source_name(reference: str) -> str:
    """Part of a reference that names the source, without retrieval date (e.g. 'Biagi-v7.1 database')"""
    return reference.split(',', maxsplit=1)[0].strip().lower()


def values_equal(a: AttrValue, b: AttrValue, rtol: float) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return bool(np.isclose(float(a), float(b), rtol=rtol, atol=0.0))
    if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        array_a, array_b = np.asarray(a), np.asarray(b)
        return array_a.shape == array_b.shape and bool(np.allclose(array_a.astype(float), array_b.astype(float), rtol=rtol, atol=0.0))
    return normalize_strings(a) == normalize_strings(b)


def normalize_strings(value: AttrValue) -> AttrValue:
    """Single-element string lists equal plain strings (e.g. ReactionModel stored as array or as string)"""
    if isinstance(value, list) and len(value) == 1:
        return normalize_strings(value[0])
    return value


def compare_attributes(path: str, a: dict[str, AttrValue], b: dict[str, AttrValue], rtol: float) -> list[Difference]:
    differences = []
    for name in sorted(set(a) | set(b)):
        if name not in b:
            differences.append(Difference(Change.ATTRIBUTE, path, f"attribute '{name}' only in A"))
        elif name not in a:
            differences.append(Difference(Change.ATTRIBUTE, path, f"attribute '{name}' only in B"))
        elif not values_equal(a[name], b[name], rtol):
            differences.append(Difference(Change.ATTRIBUTE, path, f"attribute '{name}': {short(a[name])} -> {short(b[name])}"))
    return differences


def short(value: AttrValue) -> str:
    text = repr(value.tolist() if isinstance(value, np.ndarray) else value)
    return text if len(text) <= 60 else text[:57] + '...'


def constant_factor(a: np.ndarray, b: np.ndarray, rtol: float) -> Optional[float]:
    """Factor f with b = f * a for all non-zero values, None if the ratio is not constant"""
    mask = (np.abs(a) > 0.0) & (np.abs(b) > 0.0)
    if mask.sum() < 2:
        return None
    ratio = b[mask] / a[mask]
    if np.ptp(ratio) <= max(rtol, 1.0e-9) * abs(float(np.mean(ratio))):
        return float(np.mean(ratio))
    return None


# ----------------------------------------------------------------------------------------------------------------------------------
# Electronic levels
# ----------------------------------------------------------------------------------------------------------------------------------
def level_state(species: Species) -> str:
    if species.electronic_placeholder:
        return 'placeholder'
    return 'no levels' if species.electronic_levels is None else f'{len(species.electronic_levels)} levels'


def compare_levels(path: str, a: Species, b: Species, rtol: float) -> list[Difference]:
    # Species references usually describe other properties (e.g. heat of formation), so they are not used to identify the source
    source = False
    if a.electronic_levels is None or b.electronic_levels is None:
        state_a, state_b = level_state(a), level_state(b)
        if state_a != state_b:
            return [Difference(Change.STRUCTURE, path, f'{state_a} in A, {state_b} in B', source)]
        return []
    levels_a, levels_b = a.electronic_levels, b.electronic_levels
    if levels_a.shape == levels_b.shape and np.allclose(levels_a, levels_b, rtol=rtol, atol=0.0):
        return []

    if levels_a.shape == levels_b.shape:
        messages = []
        factor = constant_factor(levels_a[:, 1], levels_b[:, 1], rtol)
        if factor is not None and not np.isclose(factor, 1.0, rtol=rtol):
            messages.append(f'all energies scaled by {factor:.8g} (B/A; different unit conversion?)')
        elif not np.allclose(levels_a[:, 1], levels_b[:, 1], rtol=rtol, atol=0.0):
            deviation = np.abs(levels_b[:, 1] - levels_a[:, 1]) / np.maximum(np.abs(levels_a[:, 1]), 1.0)
            messages.append(f'{int(np.sum(deviation > rtol))} energies differ (max relative deviation {deviation.max():.2e})')
        changed = np.flatnonzero(levels_a[:, 0] != levels_b[:, 0])
        if changed.size:
            first = int(changed[0])
            messages.append(f'{changed.size} degeneracies differ (first: level {first}, {levels_a[first, 0]:g} -> {levels_b[first, 0]:g})')
        scaled = factor is not None and not np.isclose(factor, 1.0, rtol=rtol)
        change = Change.SCALED if scaled and len(messages) == 1 else Change.NUMERIC
        return [Difference(change, path, '; '.join(messages), source)]

    # Different number of levels: match energies after sorting, also after scaling with the ratio of the first excited levels
    energies_a, energies_b = np.sort(levels_a[:, 1]), np.sort(levels_b[:, 1])
    matched_a, matched_b = match_energies(energies_a, energies_b)
    factor = None
    excited_a, excited_b = energies_a[energies_a > 0.0], energies_b[energies_b > 0.0]
    if excited_a.size and excited_b.size:
        candidate = float(excited_b[0] / excited_a[0])
        if not np.isclose(candidate, 1.0, rtol=rtol):
            scaled_a, scaled_b = match_energies(energies_a * candidate, energies_b)
            enough = scaled_a.sum() >= 0.5 * min(len(energies_a), len(energies_b))
            if enough and scaled_a.sum() > max(matched_a.sum(), 1) * 1.5:
                factor, matched_a, matched_b = candidate, scaled_a, scaled_b
    message = f'{len(levels_a)} levels in A, {len(levels_b)} in B'
    if factor is not None:
        message += f'; energies scaled by {factor:.8g} (B/A; different unit conversion?)'
    message += f'; {int((~matched_a).sum())} energies only in A, {int((~matched_b).sum())} only in B; sum of degeneracies {levels_a[:, 0].sum():g} -> {levels_b[:, 0].sum():g}'
    ground_a, ground_b = levels_a[np.argmin(levels_a[:, 1])], levels_b[np.argmin(levels_b[:, 1])]
    if not np.array_equal(ground_a, ground_b):
        message += f'; lowest level {ground_a.tolist()} -> {ground_b.tolist()}'
    return [Difference(Change.NUMERIC, path, message, source)]


def match_energies(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Which energies of a have a counterpart in b and vice versa (relative tolerance 1e-6)"""
    close = np.isclose(a[:, None], b[None, :], rtol=1.0e-6, atol=1.0e-9)
    return close.any(axis=1), close.any(axis=0)


# ----------------------------------------------------------------------------------------------------------------------------------
# Cross-sections
# ----------------------------------------------------------------------------------------------------------------------------------
def canonical_pair(name: str) -> str:
    return '-'.join(sorted(name.split('-', 1)))


def effective_kind(xsec: CrossSection) -> XSecKind:
    """Kind used for matching; unknown names that are probable typos (e.g. ELECTRONIIC) count as the intended kind"""
    if xsec.kind is XSecKind.UNKNOWN:
        matches = difflib.get_close_matches(xsec.group or xsec.key, KIND_NAMES, n=1, cutoff=0.6)
        if matches:
            return XSecKind(matches[0])
    return xsec.kind


def matching_key(xsec: CrossSection) -> tuple[str, str]:
    kind = effective_kind(xsec)
    if kind in XSEC_THRESHOLD_KINDS:
        try:
            return kind.value, f'{float(xsec.key):.6g}'
        except ValueError:
            return kind.value, xsec.key
    if kind is XSecKind.REACTION:
        return kind.value, '-'.join(sorted(xsec.key.split('-')))
    return kind.value, xsec.key


def keyed(cross_sections: list[CrossSection]) -> dict[tuple[str, str], CrossSection]:
    """Cross-sections by matching key; entries whose keys coincide (e.g. thresholds '14' and '14.0') keep their exact names"""
    counts: dict[tuple[str, str], int] = {}
    for xsec in cross_sections:
        counts[matching_key(xsec)] = counts.get(matching_key(xsec), 0) + 1
    return {(matching_key(xsec) if counts[matching_key(xsec)] == 1 else (effective_kind(xsec).value, xsec.key)): xsec for xsec in cross_sections}


def display_path(pair: str, xsec: CrossSection) -> str:
    return f'/Cross-Sections/{pair}/' + (f'{xsec.group}/' if xsec.group else '') + xsec.key


def compare_curves(path: str, a: CrossSection, b: CrossSection, rtol: float, source: bool = False) -> list[Difference]:
    data_a, data_b = a.data, b.data
    if data_a.shape == data_b.shape and np.allclose(data_a, data_b, rtol=rtol, atol=0.0):
        return []
    if data_a.ndim != 2 or data_b.ndim != 2 or data_a.shape[1] != 2 or data_b.shape[1] != 2 or len(data_a) < 2 or len(data_b) < 2:
        return [Difference(Change.STRUCTURE, path, f'shape {data_a.shape} -> {data_b.shape}', source)]

    same_grid = data_a.shape == data_b.shape and np.allclose(data_a[:, 0], data_b[:, 0], rtol=rtol, atol=0.0)
    if same_grid:
        energy, sigma_a, sigma_b = data_a[:, 0], data_a[:, 1], data_b[:, 1]
        grid = 'same energy grid'
    else:
        # Compare on the union of both grids within the common energy range
        low, high = max(data_a[0, 0], data_b[0, 0]), min(data_a[-1, 0], data_b[-1, 0])
        energy = np.union1d(data_a[:, 0], data_b[:, 0])
        energy = energy[(energy >= low) & (energy <= high)]
        if energy.size == 0:
            return [Difference(Change.NUMERIC, path, 'energy ranges do not overlap', source)]
        sigma_a, sigma_b = np.interp(energy, data_a[:, 0], data_a[:, 1]), np.interp(energy, data_b[:, 0], data_b[:, 1])
        grid = f'{len(data_a)} -> {len(data_b)} points, compared on {low:g}-{high:g} eV'

    # Relative deviation where the cross-section is significant (above 1 % of its maximum)
    scale = max(float(np.max(np.abs(sigma_a))), float(np.max(np.abs(sigma_b))), 1.0e-300)
    significant = np.maximum(np.abs(sigma_a), np.abs(sigma_b)) > 0.01 * scale
    deviation = np.zeros_like(sigma_a)
    deviation[significant] = (sigma_b[significant] - sigma_a[significant]) / np.maximum(np.abs(sigma_a[significant]), 1.0e-300)
    if not significant.any() or np.max(np.abs(deviation)) <= rtol:
        if same_grid:
            return []
        return [Difference(Change.STRUCTURE, path, f'same cross-section on a different energy grid ({grid})', source)]

    factor = constant_factor(sigma_a, sigma_b, rtol) if same_grid else None
    if factor is not None:
        return [Difference(Change.SCALED, path, f'cross-section scaled by {factor:.6g} (B/A; unit conversion?)', source)]
    worst = int(np.argmax(np.abs(deviation)))
    affected = energy[np.abs(deviation) > rtol]
    message = f'max deviation {deviation[worst]:+.2%} at {energy[worst]:g} eV, median {np.median(deviation[significant]):+.2%}, deviations from {float(np.min(affected)):g} to {float(np.max(affected)):g} eV ({grid})'
    return [Difference(Change.NUMERIC, path, message, source)]


def compare_cross_sections(a: Database, b: Database, rtol: float, comparison: Comparison) -> None:
    pairs_a = {canonical_pair(name): pair for name, pair in a.collision_pairs.items()}
    pairs_b = {canonical_pair(name): pair for name, pair in b.collision_pairs.items()}
    for key in sorted(set(pairs_a) | set(pairs_b)):
        if key not in pairs_b:
            comparison.differences.append(Difference(Change.ONLY_IN_A, f'/Cross-Sections/{pairs_a[key].name}', 'collision pair only in A'))
            continue
        if key not in pairs_a:
            comparison.differences.append(Difference(Change.ONLY_IN_B, f'/Cross-Sections/{pairs_b[key].name}', 'collision pair only in B'))
            continue
        pair_a, pair_b = pairs_a[key], pairs_b[key]
        if pair_a.name != pair_b.name:
            comparison.differences.append(Difference(Change.RENAMED, f'/Cross-Sections/{pair_b.name}', f'collision pair stored as {pair_a.name} in A'))
        xsecs_a, xsecs_b = keyed(pair_a.cross_sections), keyed(pair_b.cross_sections)
        for match in sorted(set(xsecs_a) | set(xsecs_b)):
            if match not in xsecs_b:
                xsec = xsecs_a[match]
                comparison.differences.append(Difference(Change.ONLY_IN_A, display_path(pair_a.name, xsec), f'{effective_kind(xsec).value} cross-section only in A'))
                continue
            if match not in xsecs_a:
                xsec = xsecs_b[match]
                comparison.differences.append(Difference(Change.ONLY_IN_B, display_path(pair_b.name, xsec), f'{effective_kind(xsec).value} cross-section only in B'))
                continue
            xsec_a, xsec_b = xsecs_a[match], xsecs_b[match]
            path = display_path(pair_b.name, xsec_b)
            # The reference is stored on the dataset or, in some files, only on the collision pair
            reference_a = xsec_a.provenance if xsec_a.provenance.reference else pair_a.provenance
            reference_b = xsec_b.provenance if xsec_b.provenance.reference else pair_b.provenance
            differences = compare_curves(path, xsec_a, xsec_b, rtol, different_source(reference_a, reference_b))
            name_a = display_path(pair_b.name, xsec_a)  # names within the pair, a renamed pair is reported once above
            if name_a != path:
                differences.append(Difference(Change.RENAMED, path, f'stored as {display_path(pair_a.name, xsec_a)} in A'))
            if differences:
                comparison.differences.extend(differences)
            else:
                comparison.identical += 1


# ----------------------------------------------------------------------------------------------------------------------------------
# Species, reactions, diffusion and surface data
# ----------------------------------------------------------------------------------------------------------------------------------
def compare_vibrational(path: str, a: Species, b: Species, rtol: float) -> list[Difference]:
    """Vibrational levels (one energy per row): present in one file only, number of levels, energies"""
    levels_a, levels_b = a.vibrational_levels, b.vibrational_levels
    if levels_a is None and levels_b is None:
        return []
    if levels_a is None or levels_b is None:
        state_a = 'no levels' if levels_a is None else f'{len(levels_a)} levels'
        state_b = 'no levels' if levels_b is None else f'{len(levels_b)} levels'
        return [Difference(Change.STRUCTURE, path, f'{state_a} in A, {state_b} in B')]
    if levels_a.shape != levels_b.shape:
        return [Difference(Change.STRUCTURE, path, f'{len(levels_a)} levels in A, {len(levels_b)} levels in B')]
    if np.allclose(levels_a, levels_b, rtol=rtol, atol=0.0):
        return []
    deviation = np.abs(levels_b - levels_a) / np.maximum(np.abs(levels_a), 1.0)
    return [Difference(Change.NUMERIC, path, f'{int(np.sum(deviation > rtol))} energies differ (max relative deviation {deviation.max():.2e})')]


def compare_species(a: Database, b: Database, rtol: float, comparison: Comparison) -> None:
    for name in sorted(set(a.species) | set(b.species)):
        if name not in b.species:
            comparison.differences.append(Difference(Change.ONLY_IN_A, f'/Species/{name}', 'species only in A'))
            continue
        if name not in a.species:
            comparison.differences.append(Difference(Change.ONLY_IN_B, f'/Species/{name}', 'species only in B'))
            continue
        species_a, species_b = a.species[name], b.species[name]
        differences = compare_levels(f'/Species/{name}/ElectronicLevel', species_a, species_b, rtol)
        differences += compare_vibrational(f'/Species/{name}/VibrationalLevel', species_a, species_b, rtol)
        # Attributes only exist in the current layout; a legacy electronic database has none
        if species_a.attributes and species_b.attributes:
            differences += compare_attributes(f'/Species/{name}', species_a.attributes, species_b.attributes, rtol)
        if differences:
            comparison.differences.extend(differences)
        else:
            comparison.identical += 1


def compare_reactions(a: Database, b: Database, rtol: float, comparison: Comparison) -> None:
    for name in sorted(set(a.reactions) | set(b.reactions)):
        if name not in b.reactions:
            comparison.differences.append(Difference(Change.ONLY_IN_A, f'/Reactions/{name}', 'reaction only in A'))
        elif name not in a.reactions:
            comparison.differences.append(Difference(Change.ONLY_IN_B, f'/Reactions/{name}', 'reaction only in B'))
        else:
            differences = compare_attributes(f'/Reactions/{name}', a.reactions[name].attributes, b.reactions[name].attributes, rtol)
            if differences:
                comparison.differences.extend(differences)
            else:
                comparison.identical += 1


def compare_tables(path: str, a: Optional[np.ndarray], b: Optional[np.ndarray], rtol: float) -> list[Difference]:
    if a is None or b is None or a.shape != b.shape:
        return [Difference(Change.STRUCTURE, path, f'shape {None if a is None else a.shape} -> {None if b is None else b.shape}')]
    if a.dtype.kind in 'fiu' and b.dtype.kind in 'fiu' and not np.allclose(a.astype(float), b.astype(float), rtol=rtol, atol=0.0):
        return [Difference(Change.NUMERIC, path, 'values differ')]
    return []


def compare_other(a: Database, b: Database, rtol: float, comparison: Comparison) -> None:
    sets_a = {(item.pair, item.database, name): data for item in a.diffusion for name, data in item.datasets.items()}
    sets_b = {(item.pair, item.database, name): data for item in b.diffusion for name, data in item.datasets.items()}
    tables = {f'/Diffusion-Coefficients/{p}/{d}/{n}': (sets_a.get((p, d, n)), sets_b.get((p, d, n))) for p, d, n in set(sets_a) | set(sets_b)}
    for name in set(a.surface) | set(b.surface):
        entry_a, entry_b = a.surface.get(name), b.surface.get(name)
        tables[f'/Surface-Chemistry/{name}'] = (entry_a.data if entry_a else None, entry_b.data if entry_b else None)
    for path in sorted(tables):
        table_a, table_b = tables[path]
        if table_b is None:
            comparison.differences.append(Difference(Change.ONLY_IN_A, path, 'only in A'))
        elif table_a is None:
            comparison.differences.append(Difference(Change.ONLY_IN_B, path, 'only in B'))
        else:
            differences = compare_tables(path, table_a, table_b, rtol)
            comparison.differences.extend(differences)
            comparison.identical += not differences


CATEGORIES = {
    'species': (lambda db: bool(db.species), compare_species),
    'reactions': (lambda db: bool(db.reactions), compare_reactions),
    'cross-sections': (lambda db: bool(db.collision_pairs), compare_cross_sections),
    'diffusion and surface data': (lambda db: bool(db.diffusion or db.surface), compare_other),
}


def compare(a: Database, b: Database, rtol: float = DEFAULT_RTOL, everything: bool = False) -> Comparison:
    """Compare two databases of any layout

    By default only categories present in both files are compared, so that e.g. a legacy electronic state database can be compared
    with the species of a complete database. With everything=True, categories missing in one file are reported as 'only in A/B'.
    """
    comparison = Comparison(a=a.path, b=b.path)
    for name, (present, function) in CATEGORIES.items():
        in_a, in_b = present(a), present(b)
        if (in_a and in_b) or (everything and (in_a or in_b)):
            function(a, b, rtol, comparison)
            comparison.compared.append(name)
        elif in_a or in_b:
            comparison.skipped.append(f'{name} (only in {"A" if in_a else "B"})')
    return comparison
