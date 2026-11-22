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
"""Derivation of a recipe from an existing database ('piclas-db rebuild')

The provenance stored in an old file is used to find out which original data it was made of:

* cross-sections with an LXCat reference ('Biagi-v7.1 database, www.lxcat.net, ...') and an LXCat header in 'Info'
  (SPECIES: e / Ar) -> LXCat database and species; ion-neutral pairs without header (e.g. Ar-ArIon1) -> 'Ar^+ / Ar'
* cross-sections with an LXCat header but without database name: identified by species, process and update time in the LXCat
  downloads of the store (the update time is unique per LXCat process)
* electronic levels with a NIST reference, or all levels with --levels-from-nist -> NIST ASD levels of the species

Everything else cannot be rebuilt automatically and is listed. Species attributes, reactions, diffusion and surface data are not
derived from original files yet; rebuild copies them from the old file.
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import ast
import re
from dataclasses import dataclass, field
from typing import Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.model import CrossSection, Database
from piclas_db.recipe import CrossSectionSelection, LevelSelection, Recipe
from piclas_db.resolve import Requirement
from piclas_db.sources.identify import database_slug, slug
from piclas_db.sources.lxcat import canonical_process, load_lxcat
from piclas_db.store import Store, StoreEntry
# ==================================================================================================================================


@dataclass
class Derivation:
    recipe: Recipe
    unresolved: list[str] = field(default_factory=list)  # entries of the old file that cannot be rebuilt


def lxcat_database(xsec: CrossSection, pair_reference: Optional[str]) -> Optional[str]:
    """LXCat database name from a recommended reference, e.g. 'Biagi-v7.1' from 'Biagi-v7.1 database, www.lxcat.net, ...'"""
    match = re.match(r'\s*(.+?)\s+database,\s*www\.lxcat\.net', xsec.provenance.reference or pair_reference or '', re.IGNORECASE)
    return match.group(1) if match else None


def lxcat_species(xsec: CrossSection, pair: str) -> Optional[str]:
    """LXCat SPECIES from the stored header, otherwise from the pair name of ion-neutral data (Ar-ArIon1 -> 'Ar^+ / Ar')"""
    text = xsec.provenance.info
    if text:
        try:
            header = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            header = {}
        if isinstance(header, dict) and header.get('SPECIES'):
            return str(header['SPECIES'])
    match = re.fullmatch(r'(\w+?)-(\w+?)Ion1', pair) or re.fullmatch(r'(\w+?)Ion1-(\w+?)', pair)
    if match and match.group(1) == match.group(2):
        return f'{match.group(1)}^+ / {match.group(1)}'
    first, _, second = pair.partition('-')
    if 'electron' in (first, second):
        return f'e / {second if first == "electron" else first}'
    return None


def find_lxcat(store: Store, database: str, species: str) -> Optional[StoreEntry]:
    """Newest LXCat file in the store that contains the database and species"""
    target = species.rsplit('/', maxsplit=1)[-1].strip()
    matches = [
        entry
        for entry in store.entries()
        if entry.meta.get('provider') == 'lxcat'
        and any(str(item.get('name', '')).lower().startswith(database.lower()) for item in entry.meta.get('databases') or [])
        and any(key.replace(' ', '').startswith(species.replace(' ', '') + ':') for key in (entry.meta.get('processes') or {}))
        and target in (entry.meta.get('species') or [])
    ]
    return max(matches, key=lambda entry: str(entry.meta.get('retrieved') or ''), default=None)


def lxcat_header(xsec: CrossSection) -> dict[str, str]:
    """LXCat header stored in 'Info' (SPECIES, PROCESS, PARAM., COMMENT, UPDATED), empty if there is none"""
    if not xsec.provenance.info:
        return {}
    try:
        header = ast.literal_eval(xsec.provenance.info)
    except (ValueError, SyntaxError):
        return {}
    return {str(key): str(value) for key, value in header.items()} if isinstance(header, dict) else {}


def fingerprint(species: str, process: str, updated: str) -> tuple[str, str, str]:
    """Species, process (canonical: TXT and XML spelling alike) and update time of an LXCat process"""
    return species.replace(' ', ''), canonical_process(process).replace(' ', ''), updated.strip()


def lxcat_index(store: Store) -> dict[tuple[str, str, str], tuple[str, StoreEntry]]:
    """Every LXCat process in the store by species, process and update time (unique per process in LXCat) -> database, file"""
    index: dict[tuple[str, str, str], tuple[str, StoreEntry]] = {}
    for entry in store.entries():
        if entry.meta.get('provider') != 'lxcat' or entry.meta.get('kind') != 'cross-sections':
            continue
        try:
            parsed = load_lxcat(entry.path)
        except (OSError, ValueError):
            continue
        for process in parsed.processes:
            if process.updated:
                index[fingerprint(process.species, process.process, process.updated)] = (process.database, entry)
    return index


def derive(database: Database, store: Store, levels_from_nist: bool = False) -> Derivation:
    derivation = Derivation(recipe=Recipe(path=f'derived from {database.path}'))
    selections: dict[tuple[str, str], CrossSectionSelection] = {}
    index = lxcat_index(store)

    for pair in database.collision_pairs.values():
        # Database of each LXCat species in this pair, for cross-sections without reference (e.g. ionization written by
        # create_xsec_db_lxcat.py without 'Reference')
        known: dict[str, str] = {}
        for xsec in pair.cross_sections:
            lxcat, species = lxcat_database(xsec, pair.provenance.reference), lxcat_species(xsec, pair.name)
            if lxcat and species:
                known.setdefault(species.replace(' ', ''), lxcat)
        for xsec in pair.cross_sections:
            name = f'{pair.name}/' + (f'{xsec.group}/' if xsec.group else '') + xsec.key
            species = lxcat_species(xsec, pair.name)
            lxcat = lxcat_database(xsec, pair.provenance.reference) or (known.get(species.replace(' ', '')) if species and xsec.provenance.info else None)
            header = lxcat_header(xsec)
            match = index.get(fingerprint(header.get('SPECIES', ''), header.get('PROCESS', ''), header.get('UPDATED', ''))) if header.get('UPDATED') else None
            if lxcat is None and match is not None:
                # Identified by the LXCat header (species, process and update time) in a download in the store
                lxcat = re.split(r'\s+database|\s*\(', match[0], maxsplit=1)[0].strip()
                species = header['SPECIES']
            if not lxcat or not species:
                reason = 'no LXCat reference' if not lxcat else 'LXCat species unknown'
                derivation.unresolved.append(f'/Cross-Sections/{name}: {reason} ({xsec.provenance.reference or "no reference"})')
                continue
            key = (lxcat.lower(), species.replace(' ', ''))
            if key not in selections:
                entry = find_lxcat(store, lxcat, species)
                target = species.rsplit('/', maxsplit=1)[-1].strip()
                source = (
                    Requirement(provider='lxcat', dataset=str(entry.meta['dataset']), sha256=str(entry.meta['sha256'])[:8]) if entry else Requirement(provider='lxcat', dataset=f'{database_slug(lxcat)}/{slug(target)}')
                )
                selections[key] = CrossSectionSelection(source=source, species=species, database=lxcat, pair=pair.name)

    derivation.recipe.cross_sections = list(selections.values())

    for species_entry in database.species.values():
        if species_entry.electronic_levels is None:
            continue
        reference = species_entry.provenance.reference or ''
        if levels_from_nist or 'nist' in reference.lower():
            derivation.recipe.levels.append(LevelSelection(source=Requirement('nist-asd', f'levels/{slug(species_entry.name)}'), species=species_entry.name))
        else:
            derivation.unresolved.append(f'/Species/{species_entry.name}/ElectronicLevel: no NIST reference (use --levels-from-nist)')
    return derivation


def recipe_yaml(recipe: Recipe, unresolved: list[str]) -> dict[str, object]:
    data: dict[str, object] = {'description': recipe.path}
    if recipe.cross_sections:
        data['cross_sections'] = [{'source': str(selection.source), 'database': selection.database, 'species': selection.species, 'pair': selection.pair} for selection in recipe.cross_sections]
    if recipe.levels:
        data['levels'] = [{'source': str(selection.source), 'species': selection.species} | ({} if selection.estimated else {'estimated': False}) for selection in recipe.levels]
    if recipe.masses != 'record':
        data['masses'] = recipe.masses
    if recipe.charges != 'data':
        data['charges'] = recipe.charges
    if unresolved:
        data['notes'] = ['No usable provenance in the old file (rebuilt only if the selected original data contain them):', *unresolved]
    return data
