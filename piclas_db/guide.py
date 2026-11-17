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
"""Step-by-step download instructions ('piclas-db guide'), taken from guides.yaml"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import importlib.resources
import re
from functools import cache

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import yaml

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.resolve import Requirement
# ==================================================================================================================================

ROMAN = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X']


@cache
def guides() -> dict[str, dict]:
    text = importlib.resources.files('piclas_db').joinpath('guides.yaml').read_text(encoding='utf-8')
    return yaml.safe_load(text)


def spectrum(species: str) -> str:
    """NIST spectrum name of a PICLas species: 'Ar' -> 'Ar I', 'ArIon1' -> 'Ar II'"""
    match = re.fullmatch(r'([A-Z][a-z]?)(?:Ion(\d+))?', species, re.IGNORECASE)
    if not match:
        return species
    charge = int(match.group(2) or 0)
    element = match.group(1).capitalize()
    return f'{element} {ROMAN[charge]}' if charge < len(ROMAN) else species


def placeholders(requirement: Requirement) -> dict[str, str]:
    if requirement.provider == 'lxcat':
        databases, _, species = requirement.dataset.partition('/')
        names = [name.capitalize() for name in databases.split('+')]
        return {
            'databases': ', '.join(names),
            'species': ', '.join(part.capitalize() if len(part) <= 2 else part for part in species.split('+')),
            'permlinks': ', '.join(f'https://www.lxcat.net/{name}' for name in names),
        }
    if requirement.provider == 'nist-asd':
        species = requirement.dataset.rsplit('/', 1)[-1]
        name = re.sub(r'ion(\d+)$', r'Ion\1', species.capitalize())
        return {'spectrum': spectrum(name), 'spectrum_file': spectrum(name).replace(' ', '_') + '_levels', 'species': name}
    return {'dataset': requirement.dataset}


def guide(requirement: Requirement) -> list[str]:
    """Lines of the instructions for one original file"""
    provider = guides().get(requirement.provider, guides()['custom'])
    values = placeholders(requirement)
    lines = [f'{requirement} ({provider["name"]})']
    for number, step in enumerate(provider['steps'], start=1):
        lines.append(f'  {number}. {fill(step, values)}')
    lines.append(f'  Terms: {" ".join(provider["terms"].split())}')
    return lines


def fill(text: str, values: dict[str, str]) -> str:
    """Replace the {placeholders} that have a value, keep the others"""
    return re.sub(r'\{(\w+)\}', lambda match: values.get(match.group(1), match.group(0)), text)
