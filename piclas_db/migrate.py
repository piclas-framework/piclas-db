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
"""Conversion of a database of any layout into the current layout ('piclas-db migrate')

Without options, migrate only changes the layout and the representation: legacy groups are moved to /Cross-Sections and
/Species, all data become float64, PICLas strings become fixed-length ASCII, metadata are written in one scheme and empty groups
are dropped. The data PICLas uses stay exactly the same, so existing parameter.ini files keep working.

--fix additionally applies corrections that change what PICLas reads: group and attribute names with typos are renamed (e.g.
ELECTRONIIC -> ELECTRONIC, alpha -> alphaVSS) and electronic levels are sorted. --canonical-products renames reaction
cross-sections to the conventional product order (heavy species first, electrons last); parameter.ini files have to list the
products in the same order. Renames that would collide with an existing entry are skipped and reported.
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import difflib
from dataclasses import dataclass, field

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import numpy as np

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.model import XSEC_GROUP_KINDS, Database, XSecKind
from piclas_db.reference import SPECIES_ATTRIBUTES
from piclas_db.schema import Schema
# ==================================================================================================================================

GROUP_NAMES = [kind.value for kind in XSEC_GROUP_KINDS]


@dataclass
class MigrationReport:
    normalized: list[str] = field(default_factory=list)  # representation only, PICLas reads the same data
    fixed: list[str] = field(default_factory=list)  # corrections that change what PICLas reads
    skipped: list[str] = field(default_factory=list)  # corrections that could not be applied
    notes: list[str] = field(default_factory=list)


def normalize(database: Database, report: MigrationReport) -> None:
    """Changes of the representation only (applied by the writer, reported here)"""
    if database.schema is Schema.LEGACY_XSEC:
        report.normalized.append(f'{len(database.collision_pairs)} collision pair(s) moved from the root to /Cross-Sections')
    if database.schema is Schema.LEGACY_ELECTRONIC:
        report.normalized.append(f'{len(database.species)} level set(s) moved from the root to /Species/<name>/ElectronicLevel')
        report.notes.append('the source has no species attributes: the result only provides electronic levels and is not a complete species database')
    float32 = sum(xsec.dtype == 'float32' for pair in database.collision_pairs.values() for xsec in pair.cross_sections)
    float32 += sum(species.dtypes.get('ElectronicLevel') == 'float32' for species in database.species.values())
    if float32:
        report.normalized.append(f'{float32} dataset(s) converted from float32 to float64')
    empty = sum(len(pair.empty_groups) for pair in database.collision_pairs.values())
    if empty:
        report.normalized.append(f'{empty} empty group(s) dropped')
        for pair in database.collision_pairs.values():
            pair.empty_groups = []
    if database.collision_pairs:
        report.normalized.append("cross-section metadata written as 'Type', 'Threshold [eV]', 'Reference', 'Info'")


def fix_group_names(database: Database, report: MigrationReport) -> None:
    for pair in database.collision_pairs.values():
        renames: dict[str, str] = {}
        for xsec in pair.of_kind(XSecKind.UNKNOWN):
            name = xsec.group or xsec.key
            matches = difflib.get_close_matches(name, GROUP_NAMES, n=1, cutoff=0.6)
            if xsec.group and matches:
                renames[xsec.group] = matches[0]
        for old, new in renames.items():
            moving = [xsec for xsec in pair.cross_sections if xsec.group == old]
            existing = {xsec.key for xsec in pair.cross_sections if xsec.group == new}
            collisions = sorted(existing & {xsec.key for xsec in moving})
            if collisions:
                report.skipped.append(f'{pair.name}: {old} -> {new} not renamed, {new} already contains {", ".join(collisions)}')
                continue
            for xsec in moving:
                xsec.group, xsec.kind = new, XSecKind(new)
            report.fixed.append(f'{pair.name}: group {old} renamed to {new} ({len(moving)} dataset(s) now read by PICLas)')


def fix_attribute_names(database: Database, report: MigrationReport) -> None:
    for species in database.species.values():
        for name in [name for name in species.attributes if name not in SPECIES_ATTRIBUTES and not name.startswith('* ')]:
            matches = difflib.get_close_matches(name, list(SPECIES_ATTRIBUTES), n=1, cutoff=0.6)
            if not matches:
                continue
            if matches[0] in species.attributes:
                report.skipped.append(f'{species.name}: attribute {name} not renamed, {matches[0]} already exists')
                continue
            species.attributes[matches[0]] = species.attributes.pop(name)
            report.fixed.append(f'{species.name}: attribute {name} renamed to {matches[0]}')


def fix_level_order(database: Database, report: MigrationReport) -> None:
    for species in database.species.values():
        levels = species.electronic_levels
        if levels is not None and np.any(np.diff(levels[:, 1]) < 0.0):
            species.electronic_levels = levels[np.argsort(levels[:, 1], kind='stable')]
            report.fixed.append(f'{species.name}: electronic levels sorted by energy')


def canonical_products(key: str) -> str:
    products = key.split('-')
    heavy = [name for name in products if name != 'electron']
    return '-'.join(heavy + ['electron'] * (len(products) - len(heavy)))


def fix_product_order(database: Database, report: MigrationReport) -> None:
    for pair in database.collision_pairs.values():
        reactions = pair.of_kind(XSecKind.REACTION)
        targets = [canonical_products(xsec.key) for xsec in reactions]
        for xsec, target in zip(reactions, targets, strict=True):
            if target == xsec.key:
                continue
            if targets.count(target) > 1 or target in {other.key for other in reactions if other is not xsec}:
                report.skipped.append(f'{pair.name}: {xsec.key} not renamed, {target} is ambiguous (several channels with the same products)')
                continue
            report.fixed.append(f'{pair.name}: reaction {xsec.key} renamed to {target} (parameter.ini must list the products in this order)')
            xsec.key = target


def migrate(database: Database, fix: bool = False, products: bool = False) -> MigrationReport:
    """Prepare the data model for writing in the current layout; modifies the database in place"""
    report = MigrationReport()
    normalize(database, report)
    if fix:
        fix_group_names(database, report)
        fix_attribute_names(database, report)
        fix_level_order(database, report)
    if products:
        fix_product_order(database, report)
    return report
