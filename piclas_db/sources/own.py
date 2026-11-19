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
"""Own data: values that come from no download (PICLas parameters such as VHS/VSS, InteractionID, characteristic temperatures), kept
as a YAML file in the store, i.e. in the private source repository, next to all other data: one location for everything.

    format: piclas-db own data
    format_version: 1
    name: piclas-parameters
    description: PICLas parameters of species (VHS/VSS, InteractionID, characteristic temperatures)
    species:
      Ar:  {Tref: 273, dref: 4.17e-10, omega: 0.31, alphaVSS: 1.4, InteractionID: 1, Reference: "Bird 1994, Table A1"}
      N2:  {Tref: 273, dref: 4.17e-10, omega: 0.24, alphaVSS: 1.36, InteractionID: 2, CharaTempVib: 3393.3, CharaTempRot: 2.87,
            Reference: "Bird 1994; Huber and Herzberg 1979"}

Every species needs a 'Reference' (where the values come from). A recipe uses the file with 'own_data: own/piclas-parameters'.

own_data_from_database() writes such a file from the species of an existing database (piclas-db export --own-data), with the reference
of each species split into the values it names (e.g. 'Moments of Inertia' -> MomentOfInertia) and the values without a named source.
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import re
from dataclasses import dataclass, field
from typing import Any

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import numpy as np
import yaml

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.common.names import name_problems
from piclas_db.model import Database, Provenance
# ==================================================================================================================================

FORMAT = 'piclas-db own data'
VERSION = 1


class OwnDataError(Exception):
    """Own-data file cannot be used"""


def is_own_data(text: str) -> bool:
    return f'format: {FORMAT}' in text[:2000]


def parse_own_data(text: str) -> dict[str, Any]:
    """Content of an own-data file, checked: format, name, species with attributes and a Reference each"""
    try:
        content = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        raise OwnDataError(f'YAML cannot be read: {e}') from e
    if not isinstance(content, dict) or content.get('format') != FORMAT:
        raise OwnDataError(f'not a piclas-db own-data file (format: {FORMAT})')
    if int(content.get('format_version', 0)) > VERSION:
        raise OwnDataError(f'format version {content["format_version"]} is newer than supported ({VERSION})')
    if not content.get('name'):
        raise OwnDataError('"name" required (the dataset name in the store, e.g. piclas-parameters)')
    species = content.get('species') or {}
    if not isinstance(species, dict) or not species:
        raise OwnDataError('"species" with at least one species required')
    problems = name_problems(species, 'species')
    for name, attributes in species.items():
        if not isinstance(attributes, dict):
            problems.append(f'{name}: attributes must be a mapping')
        elif not str(attributes.get('Reference', '')).strip():
            problems.append(f'{name}: "Reference" missing (where do the values come from?)')
    if problems:
        raise OwnDataError('; '.join(problems))
    return content


# ----------------------------------------------------------------------------------------------------------------------------------
# Own data from an existing database
# ----------------------------------------------------------------------------------------------------------------------------------
# Labels used in references of existing files and the attributes they stand for (None: not an attribute, e.g. levels)
REFERENCE_LABELS: tuple[tuple[str, str | None], ...] = (
    (r'heat\s*of\s*formation', 'HeatOfFormation_K'),
    (r'moments?\s*of\s*inertia', 'MomentOfInertia'),
    (r'electronic\s*(energy\s*)?levels?', None),
    (r'vibrational\s*(energy\s*)?levels?', None),
)
ATCT_ATTRIBUTES = ('HeatOfFormation_K', 'MassIC')  # what a recipe takes from ATcT ('atct:' ID)
UNKNOWN_REFERENCES = ('', 'unknown', 'none', 'n/a')
ORDER = ('MassIC', 'ChargeIC', 'HeatOfFormation_K', 'InteractionID', 'PreviousState', 'Tref', 'dref', 'omega', 'alpha', 'alphaVSS')


@dataclass
class OwnDataExport:
    """Own-data content written from a database, with what was left out"""

    content: dict[str, Any]
    atct_species: list[str] = field(default_factory=list)  # species whose reference names ATcT
    left_out: dict[str, list[str]] = field(default_factory=dict)  # species -> attributes left out (values from ATcT)
    unknown: dict[str, list[str]] = field(default_factory=dict)  # species -> attributes without a named source


def label_attribute(label: str, attributes: dict[str, Any]) -> str | None:
    """Attribute a reference label stands for: an attribute name, a known label, None for non-attributes (levels), '' if unknown"""
    if label in attributes or label in ATCT_ATTRIBUTES:
        return label
    return next((attribute for pattern, attribute in REFERENCE_LABELS if re.fullmatch(pattern + r'(\s*\[.*\])?', label.strip(), re.IGNORECASE)), '')


def split_reference(provenance: Provenance, attributes: dict[str, Any]) -> tuple[dict[str | None, str], list[str]]:
    """Reference of a species split into the parts with a known label (attribute -> text; None: not an attribute, e.g. levels) and
    other text. Tabular references give the labels; a plain reference is split at '; ', a part 'Label: text' with a known label"""
    if provenance.reference_parts:
        rows = [(label, text, f'{label}: {text}') for label, text in provenance.reference_parts]  # (label, text, original wording)
    else:
        reference = provenance.reference or ''
        if reference.strip().lower() in UNKNOWN_REFERENCES:
            return {}, []
        rows = [(label.strip(), text, part.strip()) if separator else ('', part, part.strip()) for part in reference.split('; ') for label, separator, text in [part.partition(':')]]
    labelled: dict[str | None, str] = {}
    other: list[str] = []
    for label, text, original in rows:
        attribute = label_attribute(label, attributes) if label else ''
        if attribute != '':
            labelled[attribute] = '; '.join(filter(None, [labelled.get(attribute), text.strip()]))
        elif text.strip().lower() not in UNKNOWN_REFERENCES:
            other.append(original)
    return labelled, other


def credits_atct(labelled: dict[str | None, str]) -> bool:
    """True if the reference names ATcT as source of the heat of formation (split_reference)"""
    return 'atct' in labelled.get('HeatOfFormation_K', '').lower()


def plain(value: Any) -> Any:
    """Attribute value as a plain YAML value (lists for arrays, exact floats)"""
    if isinstance(value, np.ndarray):
        return [plain(item) for item in value.tolist()]
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def ordered(attributes: dict[str, Any]) -> dict[str, Any]:
    keys = [key for key in ORDER if key in attributes] + sorted(key for key in attributes if key not in ORDER)
    return {key: attributes[key] for key in keys}


def own_data_from_database(database: Database, origin: str, name: str = 'piclas-parameters', keep_atct: bool = False, atct: frozenset[str] = frozenset()) -> OwnDataExport:
    """Own data with every species attribute of a database; heat of formation and mass are left out for species whose reference
    credits ATcT and for the species in 'atct' (with an ATcT ID in a recipe): a recipe takes them from ATcT; keep_atct keeps the
    credited ones. Every species gets a Reference: origin, the sources named per value, the values without one"""
    export = OwnDataExport(content={})
    species_data: dict[str, dict[str, Any]] = {}
    for species_name, species in sorted(database.species.items()):
        attributes = {key: plain(value) for key, value in species.attributes.items()}
        labelled, other = split_reference(species.provenance, attributes)
        credited = credits_atct(labelled)
        if credited:
            export.atct_species.append(species_name)
        if species_name in atct or (credited and not keep_atct):
            # a recipe takes heat of formation and mass from the ATcT record, which carries its own reference
            export.left_out[species_name] = [key for key in ATCT_ATTRIBUTES if attributes.pop(key, None) is not None]
            for key in ATCT_ATTRIBUTES:
                labelled.pop(key, None)
        if not attributes:
            continue
        parts = [origin]
        named = {key for key in labelled if key in attributes}
        parts += [f'{key}: {labelled[key]}' for key in sorted(named, key=str)]
        rest = [key for key in ordered(attributes) if key not in named]
        if other and rest:
            parts.append(f'not stated which of {", ".join(rest)} come from: {"; ".join(other)}')
        elif other:
            parts.append('; '.join(other))
        elif rest:
            parts.append(f'source unknown: {", ".join(rest)}')
            export.unknown[species_name] = rest
        species_data[species_name] = {**ordered(attributes), 'Reference': '; '.join(parts)}
    export.content = {
        'format': FORMAT,
        'format_version': VERSION,
        'name': name,
        'description': f'PICLas parameters of species from {origin}' + ('' if keep_atct else ' (heats of formation and masses credited to ATcT left out)'),
        'species': species_data,
    }
    return export


def dump_own_data(content: dict[str, Any], header: list[str]) -> str:
    """Own-data file text: comment header, metadata, one line per species (flow style), checked by parse_own_data"""
    lines = [f'# {line}' if line else '#' for line in header]
    lines += [yaml.safe_dump({key: value}, sort_keys=False, allow_unicode=True, width=1000).rstrip() for key, value in content.items() if key != 'species']
    lines.append('species:')
    for species_name, attributes in content['species'].items():
        key = yaml.safe_dump(species_name).splitlines()[0]  # quoted only where YAML would read something else (e.g. 'NO')
        lines.append(f'  {key}: ' + yaml.safe_dump(attributes, sort_keys=False, allow_unicode=True, width=100000, default_flow_style=True).strip())
    text = '\n'.join(lines) + '\n'
    parse_own_data(text)
    return text
