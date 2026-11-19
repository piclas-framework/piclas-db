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
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
from typing import Any

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import yaml
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
    problems = []
    for name, attributes in species.items():
        if not isinstance(attributes, dict):
            problems.append(f'{name}: attributes must be a mapping')
        elif not str(attributes.get('Reference', '')).strip():
            problems.append(f'{name}: "Reference" missing (where do the values come from?)')
    if problems:
        raise OwnDataError('; '.join(problems))
    return content
