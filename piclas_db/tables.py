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
"""ASCII tables: human-readable, diff-able representation of a database ('piclas-db export')

The tables are input and output of the tool only; they are never stored in a repository. Layout of a table directory:

    database.yaml                         format version, layout of the source file, file and group attributes
    species.yaml                          species attributes and provenance
    species/<name>.electronic_levels.csv  degeneracy, energy [K]
    species/<name>.vibrational_levels.csv energy [K]
    reactions.yaml                        reaction attributes and provenance
    cross_sections/<pair>/metadata.yaml   provenance, kinds and thresholds of all cross-sections of the pair
    cross_sections/<pair>/[<group>/]<key>.csv  energy [eV], cross-section [m^2]
    diffusion/<pair>/<database>/...       metadata.yaml and one CSV per quantity
    surface.yaml, surface/<name>.csv      surface chemistry

Numbers are written with 17 significant digits, so that export and read-in reproduce the data exactly.
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import pathlib
from typing import Optional, Union

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import numpy as np
import yaml

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.model import (
    AttrValue,
    CollisionPair,
    CrossSection,
    Database,
    DiffusionSet,
    Provenance,
    Reaction,
    Species,
    SurfaceEntry,
    XSecKind,
)
from piclas_db.schema import Schema
# ==================================================================================================================================

FORMAT = 'piclas-db tables'
FORMAT_VERSION = 1
XSEC_HEADER = 'energy_eV,cross_section_m2'


class TablesError(Exception):
    """Directory is not a valid table export"""


# ----------------------------------------------------------------------------------------------------------------------------------
# Conversion of attribute values to YAML and back
# ----------------------------------------------------------------------------------------------------------------------------------
def to_yaml(value: AttrValue) -> object:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {key: to_yaml(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_yaml(item) for item in value]
    return value


def from_yaml(value: object) -> AttrValue:
    """Numeric lists become arrays again (as read from HDF5), string lists stay lists"""
    if isinstance(value, list) and value and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in np.ravel(np.array(value, dtype=object))):
        return np.array(value)
    return value


def provenance_to_yaml(provenance: Provenance) -> dict[str, object]:
    data: dict[str, object] = {}
    if provenance.reference is not None:
        data['reference'] = provenance.reference
    if provenance.info is not None:
        data['info'] = provenance.info
    if provenance.extra:
        data['extra'] = {key: to_yaml(value) for key, value in provenance.extra.items()}
    return data


def provenance_from_yaml(data: Optional[dict]) -> Provenance:
    data = data or {}
    extra = {key: from_yaml(value) for key, value in (data.get('extra') or {}).items()}
    return Provenance(reference=data.get('reference'), info=data.get('info'), extra=extra)


def write_yaml(path: pathlib.Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as file:
        yaml.safe_dump(data, file, sort_keys=False, allow_unicode=True, width=1000)


def read_yaml(path: pathlib.Path) -> dict:
    with path.open(encoding='utf-8') as file:
        return yaml.safe_load(file) or {}


def write_csv(path: pathlib.Path, data: np.ndarray, header: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savetxt(path, np.atleast_2d(data), delimiter=',', fmt='%.17g', header=header, comments='')


def read_csv(path: pathlib.Path) -> np.ndarray:
    return np.loadtxt(path, delimiter=',', skiprows=1, ndmin=2, dtype=np.float64)


# ----------------------------------------------------------------------------------------------------------------------------------
# Export
# ----------------------------------------------------------------------------------------------------------------------------------
def export_tables(database: Database, directory: Union[str, pathlib.Path]) -> None:
    """Write the data model as ASCII tables into a new or empty directory"""
    root = pathlib.Path(directory)
    if root.exists() and any(root.iterdir()):
        raise TablesError(f'directory is not empty: {root}')
    root.mkdir(parents=True, exist_ok=True)

    write_yaml(
        root / 'database.yaml',
        {'format': FORMAT, 'format_version': FORMAT_VERSION, 'source_layout': database.schema.name, 'attributes': to_yaml(database.attributes)},
    )

    species_data = {}
    for species in database.species.values():
        entry: dict[str, object] = {'attributes': to_yaml(species.attributes), 'provenance': provenance_to_yaml(species.provenance)}
        if species.electronic_levels is not None:
            entry['electronic_levels'] = f'species/{species.name}.electronic_levels.csv'
            write_csv(root / str(entry['electronic_levels']), species.electronic_levels, 'degeneracy,energy_K')
        elif species.electronic_placeholder:
            entry['electronic_levels'] = 'placeholder'
        if species.vibrational_levels is not None:
            entry['vibrational_levels'] = f'species/{species.name}.vibrational_levels.csv'
            write_csv(root / str(entry['vibrational_levels']), species.vibrational_levels, 'energy_K')
        species_data[species.name] = entry
    if species_data:
        write_yaml(root / 'species.yaml', species_data)

    if database.reactions:
        write_yaml(
            root / 'reactions.yaml',
            {name: {'attributes': to_yaml(reaction.attributes), 'provenance': provenance_to_yaml(reaction.provenance)} for name, reaction in database.reactions.items()},
        )

    for pair in database.collision_pairs.values():
        directory_pair = root / 'cross_sections' / pair.name
        datasets = []
        for xsec in pair.cross_sections:
            file = (f'{xsec.group}/' if xsec.group else '') + f'{xsec.key}.csv'
            write_csv(directory_pair / file, xsec.data, XSEC_HEADER)
            entry = {'file': file, 'kind': xsec.kind.value, 'group': xsec.group, 'key': xsec.key, 'threshold': xsec.threshold}
            entry['provenance'] = provenance_to_yaml(xsec.provenance)
            datasets.append(entry)
        metadata = {'provenance': provenance_to_yaml(pair.provenance), 'empty_groups': pair.empty_groups, 'cross_sections': datasets}
        write_yaml(directory_pair / 'metadata.yaml', metadata)

    for diffusion in database.diffusion:
        directory_set = root / 'diffusion' / diffusion.pair / diffusion.database
        for name, data in diffusion.datasets.items():
            write_csv(directory_set / f'{name}.csv', data, ','.join(f'column_{i}' for i in range(np.atleast_2d(data).shape[1])))
        write_yaml(directory_set / 'metadata.yaml', {'provenance': provenance_to_yaml(diffusion.provenance), 'datasets': list(diffusion.datasets)})

    surface_data = {}
    for entry_surface in database.surface.values():
        entry = {'attributes': to_yaml(entry_surface.attributes), 'provenance': provenance_to_yaml(entry_surface.provenance)}
        if entry_surface.data is not None and entry_surface.data.ndim == 2:
            entry['file'] = f'surface/{entry_surface.name}.csv'
            write_csv(root / str(entry['file']), entry_surface.data, ','.join(f'column_{i}' for i in range(entry_surface.data.shape[1])))
        surface_data[entry_surface.name] = entry
    if surface_data:
        write_yaml(root / 'surface.yaml', surface_data)


# ----------------------------------------------------------------------------------------------------------------------------------
# Read-in
# ----------------------------------------------------------------------------------------------------------------------------------
def is_tables(directory: Union[str, pathlib.Path]) -> bool:
    return (pathlib.Path(directory) / 'database.yaml').is_file()


def read_tables(directory: Union[str, pathlib.Path]) -> Database:
    """Read an ASCII table export into the data model"""
    root = pathlib.Path(directory)
    header = read_yaml(root / 'database.yaml')
    if header.get('format') != FORMAT:
        raise TablesError(f'not a piclas-db table export: {root}')
    if header.get('format_version', 0) > FORMAT_VERSION:
        raise TablesError(f'table format version {header["format_version"]} is newer than supported ({FORMAT_VERSION})')
    database = Database(path=str(root), schema=Schema.ASCII_TABLES)
    database.attributes = {key: from_yaml(value) for key, value in (header.get('attributes') or {}).items()}

    if (root / 'species.yaml').is_file():
        for name, entry in read_yaml(root / 'species.yaml').items():
            attributes = {key: from_yaml(value) for key, value in (entry.get('attributes') or {}).items()}
            species = Species(name=name, attributes=attributes, provenance=provenance_from_yaml(entry.get('provenance')))
            levels = entry.get('electronic_levels')
            if levels == 'placeholder':
                species.electronic_placeholder = True
            elif levels:
                species.electronic_levels = read_csv(root / levels)
            if entry.get('vibrational_levels'):
                species.vibrational_levels = read_csv(root / entry['vibrational_levels'])
            database.species[name] = species

    if (root / 'reactions.yaml').is_file():
        for name, entry in read_yaml(root / 'reactions.yaml').items():
            attributes = {key: from_yaml(value) for key, value in (entry.get('attributes') or {}).items()}
            database.reactions[name] = Reaction(name=name, attributes=attributes, provenance=provenance_from_yaml(entry.get('provenance')))

    for metadata_file in sorted((root / 'cross_sections').glob('*/metadata.yaml')):
        metadata = read_yaml(metadata_file)
        pair = CollisionPair(name=metadata_file.parent.name, empty_groups=list(metadata.get('empty_groups') or []))
        pair.provenance = provenance_from_yaml(metadata.get('provenance'))
        for entry in metadata.get('cross_sections') or []:
            pair.cross_sections.append(
                CrossSection(
                    kind=XSecKind(entry['kind']),
                    key=str(entry['key']),
                    data=read_csv(metadata_file.parent / entry['file']),
                    group=entry.get('group'),
                    threshold=entry.get('threshold'),
                    provenance=provenance_from_yaml(entry.get('provenance')),
                )
            )
        database.collision_pairs[pair.name] = pair

    for metadata_file in sorted((root / 'diffusion').glob('*/*/metadata.yaml')):
        metadata = read_yaml(metadata_file)
        diffusion = DiffusionSet(pair=metadata_file.parent.parent.name, database=metadata_file.parent.name)
        diffusion.provenance = provenance_from_yaml(metadata.get('provenance'))
        for name in metadata.get('datasets') or []:
            diffusion.datasets[name] = read_csv(metadata_file.parent / f'{name}.csv')
        database.diffusion.append(diffusion)

    if (root / 'surface.yaml').is_file():
        for name, entry in read_yaml(root / 'surface.yaml').items():
            attributes = {key: from_yaml(value) for key, value in (entry.get('attributes') or {}).items()}
            data = read_csv(root / entry['file']) if entry.get('file') else None
            database.surface[name] = SurfaceEntry(name=name, data=data, attributes=attributes, provenance=provenance_from_yaml(entry.get('provenance')))
    return database
