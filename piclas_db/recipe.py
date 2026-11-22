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
    literature:                              # data from papers (extraction records in the store)
      - source: literature/yoon-2008/total-ionization
        pair: H2-electron
        kind: REACTION
        key: H2Ion1-electron-electron
      - parts:                               # one cross-section from several extractions, each in an energy range (eV)
          - {source: literature/yoon-2008/table12-c1, range: [16, 25]}
          - {source: literature/yoon-2008/table13-c1, range: [30, 1000]}
        zero_at: 15.426                      # optional: sigma = 0 at the threshold
        pair: H2-electron
        kind: REACTION
        key: H2Ion1-electron-electron
    own_data: own/piclas-parameters          # PICLas parameters of the species (own-data file in the store)
    species:                                 # species of the database; values here only for tests (store them in own data)
      Ar: {MassIC: 6.63E-26, InteractionID: 1}
      CO: {atct: 630-08-0*0, InteractionID: 2} # HeatOfFormation_K and MassIC from ATcT (downloaded automatically)
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import itertools
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
from piclas_db.common.names import name_problems
from piclas_db.model import XSecKind
from piclas_db.resolve import Requirement
# ==================================================================================================================================

KINDS = [kind.value for kind in XSecKind if kind is not XSecKind.UNKNOWN]


class RecipeError(Exception):
    """Invalid recipe"""


def atct_requirement(atct_id: str) -> Requirement:
    """ATcT species record in the store (downloaded automatically if missing): 'atct: 630-08-0*0' in a species entry"""
    from piclas_db.sources.identify import atct_dataset  # noqa: PLC0415

    return Requirement('atct', atct_dataset(atct_id))


ALL_DOWNLOADS = '*'  # 'source: lxcat': the processes of all LXCat downloads in the store


@dataclass
class CrossSectionSelection:
    source: Requirement
    species: str  # LXCat SPECIES, e.g. 'e / Ar'
    database: Optional[str] = None  # start of the LXCat database name; None: the only database with this species
    pair: Optional[str] = None  # collision pair in the output; default: target-projectile in PICLas names
    processes: list[str] = field(default_factory=list)  # parts of PROCESS strings to include; empty: all
    types: dict[str, str] = field(default_factory=dict)  # LXCat type -> PICLas kind, e.g. {'Isotropic': 'ELASTIC'}


@dataclass
class LiteratureSelection:
    """Extraction from a paper (literature provider) used as one cross-section"""

    source: Requirement  # literature/<paper>/<dataset>[@sha256]; the first part if the dataset is combined from parts
    pair: str  # collision pair in PICLas names, e.g. H2-electron
    kind: str  # PICLas group: ELASTIC, EFFECTIVE, REACTION, ELECTRONIC, ...
    key: Optional[str] = None  # products for REACTION, e.g. H2Ion1-electron-electron; threshold for ELECTRONIC/VIBRATION/ROTATION
    threshold: Optional[float] = None  # eV
    parts: list[tuple[Requirement, Optional[tuple[float, float]]]] = field(default_factory=list)  # several extractions, each in an energy range
    zero_at: Optional[float] = None  # eV: sigma = 0 inserted at this energy (threshold) before the first point


@dataclass
class LevelSelection:
    source: Requirement
    species: str  # PICLas name
    estimated: bool = True  # levels with energies in brackets (theoretical or derived values in NIST ASD); false leaves them out


@dataclass
class Recipe:
    path: str
    cross_sections: list[CrossSectionSelection] = field(default_factory=list)
    levels: list[LevelSelection] = field(default_factory=list)
    literature: list[LiteratureSelection] = field(default_factory=list)
    own_data: list[Requirement] = field(default_factory=list)  # own/<name>: PICLas parameters of species, from the store
    species: dict[str, dict[str, object]] = field(default_factory=dict)  # own data: species attributes
    reactions: dict[str, dict[str, object]] = field(default_factory=dict)  # own data: reaction attributes
    masses: str = 'record'  # 'composition': MassIC of molecules and ions from their atoms (piclas_db/derive.py)
    charges: str = 'data'  # 'name': ChargeIC from the name

    @property
    def requirements(self) -> list[Requirement]:
        """Original files of the recipe ('source: lxcat' selections are found per process, not as one file)"""
        unique: dict[str, Requirement] = {}
        for selection in [*self.cross_sections, *self.levels, *self.literature]:
            if selection.source.dataset != ALL_DOWNLOADS:
                unique.setdefault(str(selection.source), selection.source)
        for literature in self.literature:
            for part, _ in literature.parts:
                unique.setdefault(str(part), part)
        for requirement in self.own_data:
            unique.setdefault(str(requirement), requirement)
        for attributes in self.species.values():
            if attributes.get('atct'):
                requirement = atct_requirement(str(attributes['atct']))
                unique.setdefault(str(requirement), requirement)
        return list(unique.values())


def requirement(entry: dict, context: str) -> Requirement:
    try:
        return Requirement.parse(str(entry['source']))
    except (KeyError, ValueError) as e:
        raise RecipeError(f'{context}: "source: <provider>/<dataset>[@sha256]" required') from e


def load_recipe(path: Union[str, pathlib.Path]) -> Recipe:
    path = pathlib.Path(path)
    try:
        text = path.read_text(encoding='utf-8')
    except OSError as e:
        raise RecipeError(f'cannot read recipe {path}: {e}') from e
    return parse_recipe(text, str(path))


def parse_recipe(text: str, path: str) -> Recipe:
    """Recipe from YAML text (e.g. the recipe embedded in a database file)"""
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        raise RecipeError(f'cannot read recipe {path}: {e}') from e
    if not isinstance(data, dict):
        raise RecipeError(f'{path}: a recipe is a mapping with cross_sections, levels, species and reactions')
    unknown = set(data) - {'cross_sections', 'levels', 'literature', 'species', 'reactions', 'own_data', 'masses', 'charges', 'description', 'notes'}
    if unknown:
        raise RecipeError(f'{path}: unknown sections {", ".join(sorted(unknown))}')

    recipe = Recipe(path=str(path))
    for key, allowed in (('masses', ('record', 'composition')), ('charges', ('data', 'name'))):
        value = str(data.get(key, allowed[0]))
        if value not in allowed:
            raise RecipeError(f'{path}: {key}: {value!r} unknown ({" or ".join(allowed)})')
        setattr(recipe, key, value)
    for number, entry in enumerate(data.get('cross_sections') or [], start=1):
        context = f'cross_sections #{number}'
        if not isinstance(entry, dict) or 'species' not in entry:
            raise RecipeError(f'{context}: "species" (LXCat SPECIES, e.g. "e / Ar") required')
        types = {str(key): str(value) for key, value in (entry.get('types') or {}).items()}
        wrong = [value for value in types.values() if value not in KINDS]
        if wrong:
            raise RecipeError(f'{context}: unknown kind(s) {", ".join(wrong)} (allowed: {", ".join(KINDS)})')
        all_downloads = str(entry.get('source', '')).strip('/') == 'lxcat'
        if all_downloads and not entry.get('database'):
            raise RecipeError(f'{context}: "source: lxcat" (all LXCat downloads in the store) needs "database"')
        recipe.cross_sections.append(
            CrossSectionSelection(
                source=Requirement('lxcat', ALL_DOWNLOADS) if all_downloads else requirement(entry, context),
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
        problems = name_problems([entry['species']], context)
        if problems:
            raise RecipeError('; '.join(problems))
        recipe.levels.append(LevelSelection(source=requirement(entry, context), species=str(entry['species']), estimated=bool(entry.get('estimated', True))))
    for number, entry in enumerate(data.get('literature') or [], start=1):
        context = f'literature #{number}'
        if not isinstance(entry, dict) or not entry.get('pair') or entry.get('kind') not in KINDS:
            raise RecipeError(f'{context}: "pair" and "kind" ({", ".join(KINDS)}) required')
        parts: list[tuple[Requirement, Optional[tuple[float, float]]]] = []
        if entry.get('parts'):
            # one cross-section from several extractions, each used in an energy range (collision energy, eV)
            for index, part in enumerate(entry['parts'], start=1):
                limits = part.get('range') if isinstance(part, dict) else None
                if not isinstance(part, dict) or not (isinstance(limits, list) and len(limits) == 2 and float(limits[0]) < float(limits[1])):
                    raise RecipeError(f'{context}, part {index}: "source" and "range: [min, max]" (eV) required')
                parts.append((requirement(part, f'{context}, part {index}'), (float(limits[0]), float(limits[1]))))
            ordered = sorted(parts, key=lambda item: item[1][0] if item[1] else 0.0)
            for (_, left), (_, right) in itertools.pairwise(ordered):
                high, low = (left or (0.0, 0.0))[1], (right or (0.0, 0.0))[0]
                if low <= high:
                    raise RecipeError(f'{context}: ranges of the parts overlap ({high:g} >= {low:g} eV)')
            parts = ordered
        selection = LiteratureSelection(
            source=parts[0][0] if parts else requirement(entry, context),
            pair=str(entry['pair']),
            kind=str(entry['kind']),
            key=str(entry['key']) if entry.get('key') is not None else None,
            threshold=float(entry['threshold']) if entry.get('threshold') is not None else None,
            parts=parts,
            zero_at=float(entry['zero_at']) if entry.get('zero_at') is not None else None,
        )
        if any(item.provider != 'literature' for item in [selection.source, *(part for part, _ in parts)]):
            raise RecipeError(f'{context}: source must be literature/<paper>/<dataset>')
        if selection.kind == 'REACTION' and not selection.key:
            raise RecipeError(f'{context}: "key" (products, e.g. H2Ion1-electron-electron) required for REACTION')
        if selection.kind in ('ELECTRONIC', 'VIBRATION', 'ROTATION') and selection.threshold is None:
            raise RecipeError(f'{context}: "threshold" (eV) required for {selection.kind}')
        recipe.literature.append(selection)
    own = data.get('own_data') or []
    for number, source in enumerate([own] if isinstance(own, str) else own, start=1):
        try:
            own_source = Requirement.parse(str(source))
        except ValueError as e:
            raise RecipeError(f'own_data #{number}: {e}') from e
        if own_source.provider != 'own':
            raise RecipeError(f'own_data #{number}: source must be own/<name> (an own-data file in the store)')
        recipe.own_data.append(own_source)
    for section in ('species', 'reactions'):
        values = data.get(section) or {}
        if not isinstance(values, dict) or not all(isinstance(value, dict) for value in values.values()):
            raise RecipeError(f'{section}: mapping of names to attributes required')
        problems = name_problems(values, section)
        if problems:
            raise RecipeError('; '.join(problems))
        setattr(recipe, section, values)
    return recipe
