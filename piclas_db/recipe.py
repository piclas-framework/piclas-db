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
"""Build recipes: which original files and which parts of them make up a database

A recipe is a YAML file. It contains no third-party data, only references to files in the store and the selection of processes,
so it can be published (e.g. recipes for the PICLas tutorials). Own data (species properties, Arrhenius parameters) can be given
inline. Example:

    cross_sections:
      - source: lxcat/biagi-v7.1+phelps/ar   # <provider>/<dataset>[@sha256] in the store
        database: Biagi                      # LXCat database in the file (start of its name)
        species: e / Ar                      # LXCat SPECIES
      - source: lxcat/biagi-v7.1+phelps/ar
        database: Phelps
        species: Ar^+ / Ar
        types: {Backscat: BACKSCATTER, Isotropic: ELASTIC}
    levels:
      - source: nist-asd/levels/ar
        species: Ar
    species:                                 # own data, written as attributes
      Ar: {MassIC: 6.63E-26, InteractionID: 1}
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import pathlib
from dataclasses import dataclass, field
from typing import Optional, Union

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import yaml

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.model import XSecKind
from piclas_db.resolve import Requirement
# ==================================================================================================================================

KINDS = [kind.value for kind in XSecKind if kind is not XSecKind.UNKNOWN]


class RecipeError(Exception):
    """Invalid recipe"""


@dataclass
class CrossSectionSelection:
    source: Requirement
    species: str  # LXCat SPECIES, e.g. 'e / Ar'
    database: Optional[str] = None  # start of the LXCat database name; None: the only database with this species
    pair: Optional[str] = None  # collision pair in the output; default: target-projectile in PICLas names
    processes: list[str] = field(default_factory=list)  # parts of PROCESS strings to include; empty: all
    types: dict[str, str] = field(default_factory=dict)  # LXCat type -> PICLas kind, e.g. {'Isotropic': 'ELASTIC'}


@dataclass
class LevelSelection:
    source: Requirement
    species: str  # PICLas name


@dataclass
class Recipe:
    path: str
    cross_sections: list[CrossSectionSelection] = field(default_factory=list)
    levels: list[LevelSelection] = field(default_factory=list)
    species: dict[str, dict[str, object]] = field(default_factory=dict)  # own data: species attributes
    reactions: dict[str, dict[str, object]] = field(default_factory=dict)  # own data: reaction attributes

    @property
    def requirements(self) -> list[Requirement]:
        unique: dict[str, Requirement] = {}
        for selection in [*self.cross_sections, *self.levels]:
            unique.setdefault(str(selection.source), selection.source)
        return list(unique.values())


def requirement(entry: dict, context: str) -> Requirement:
    try:
        return Requirement.parse(str(entry['source']))
    except (KeyError, ValueError) as e:
        raise RecipeError(f'{context}: "source: <provider>/<dataset>[@sha256]" required') from e


def load_recipe(path: Union[str, pathlib.Path]) -> Recipe:
    path = pathlib.Path(path)
    try:
        data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    except (OSError, yaml.YAMLError) as e:
        raise RecipeError(f'cannot read recipe {path}: {e}') from e
    if not isinstance(data, dict):
        raise RecipeError(f'{path}: a recipe is a mapping with cross_sections, levels, species and reactions')
    unknown = set(data) - {'cross_sections', 'levels', 'species', 'reactions', 'description', 'notes'}
    if unknown:
        raise RecipeError(f'{path}: unknown sections {", ".join(sorted(unknown))}')

    recipe = Recipe(path=str(path))
    for number, entry in enumerate(data.get('cross_sections') or [], start=1):
        context = f'cross_sections #{number}'
        if not isinstance(entry, dict) or 'species' not in entry:
            raise RecipeError(f'{context}: "species" (LXCat SPECIES, e.g. "e / Ar") required')
        types = {str(key): str(value) for key, value in (entry.get('types') or {}).items()}
        wrong = [value for value in types.values() if value not in KINDS]
        if wrong:
            raise RecipeError(f'{context}: unknown kind(s) {", ".join(wrong)} (allowed: {", ".join(KINDS)})')
        recipe.cross_sections.append(
            CrossSectionSelection(
                source=requirement(entry, context),
                species=str(entry['species']),
                database=entry.get('database'),
                pair=entry.get('pair'),
                processes=[str(process) for process in entry.get('processes') or []],
                types=types,
            )
        )
    for number, entry in enumerate(data.get('levels') or [], start=1):
        context = f'levels #{number}'
        if not isinstance(entry, dict) or 'species' not in entry:
            raise RecipeError(f'{context}: "species" (PICLas name, e.g. ArIon1) required')
        recipe.levels.append(LevelSelection(source=requirement(entry, context), species=str(entry['species'])))
    for section in ('species', 'reactions'):
        values = data.get(section) or {}
        if not isinstance(values, dict) or not all(isinstance(value, dict) for value in values.values()):
            raise RecipeError(f'{section}: mapping of names to attributes required')
        setattr(recipe, section, values)
    return recipe
