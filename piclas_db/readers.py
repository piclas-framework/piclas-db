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
"""Readers for all known database layouts, filling the layout-independent data model (piclas_db.model)"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import pathlib
from typing import Optional, Union

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import h5py
import numpy as np

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.model import (
    XSEC_DATASET_KINDS,
    XSEC_GROUP_KINDS,
    XSEC_THRESHOLD_KINDS,
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
from piclas_db.schema import Schema, detect_schema
# ==================================================================================================================================

# Attributes that only carry metadata (never read by PICLas), in all variants found in existing files
REFERENCE_ATTRIBUTES = ('Reference', '* Reference', 'Source')
INFO_ATTRIBUTES = ('Info',)
METADATA_ATTRIBUTES = ('Note', 'Comment', 'Type', 'PROCESS', 'TYPE', 'Energy Info', 'Threshold [eV]', 'columns', 'num_rows', 'num_cols', 'source_csv')


class DatabaseReadError(Exception):
    """File cannot be read as a PICLas database"""


# ----------------------------------------------------------------------------------------------------------------------------------
# Attribute decoding
# ----------------------------------------------------------------------------------------------------------------------------------
def decode(value: object) -> AttrValue:
    """Convert an HDF5 attribute value into plain Python types: strings, numbers, (nested) lists of strings or numeric arrays"""
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    if isinstance(value, np.ndarray):
        if value.dtype.kind in 'SUO':
            decoded = [decode(item) for item in value.ravel()]
            return decoded if value.ndim <= 1 else np.array(decoded, dtype=object).reshape(value.shape).tolist()
        if value.ndim == 0 or value.size == 1 and value.ndim == 1:
            return value.ravel()[0].item()
        return value
    if isinstance(value, np.generic):
        return value.item()
    return value


def flatten_text(value: AttrValue) -> str:
    """Join string attributes of any shape (e.g. [['...']] written by some converters) into one string"""
    if isinstance(value, list):
        return ' '.join(flatten_text(item) for item in value if item not in ('', None))
    return str(value)


def is_metadata(name: str) -> bool:
    """True for attributes that only carry metadata"""
    return name.startswith('* ') or name in REFERENCE_ATTRIBUTES or name in INFO_ATTRIBUTES or name in METADATA_ATTRIBUTES


def split_attributes(attrs: h5py.AttributeManager, all_metadata: bool = False) -> tuple[dict[str, AttrValue], Provenance]:
    """Split HDF5 attributes into physical attributes (read by PICLas) and provenance"""
    attributes: dict[str, AttrValue] = {}
    provenance = Provenance()
    for name in attrs:
        value = decode(attrs[name])
        if name in REFERENCE_ATTRIBUTES:
            text = flatten_text(value)
            provenance.reference = text if provenance.reference is None else f'{provenance.reference} {text}'
        elif name in INFO_ATTRIBUTES:
            provenance.info = flatten_text(value)
        elif all_metadata or is_metadata(name):
            provenance.extra[name] = value
        else:
            attributes[name] = value
    return attributes, provenance


def parse_float(text: str) -> Optional[float]:
    """Number in a dataset name (e.g. the threshold of an excitation), None if the name is not a number"""
    try:
        return float(text)
    except ValueError:
        return None


# ----------------------------------------------------------------------------------------------------------------------------------
# Datasets
# ----------------------------------------------------------------------------------------------------------------------------------
def read_array(dataset: h5py.Dataset, database: Database) -> Optional[np.ndarray]:
    """Read a dataset completely, record it as unreadable on failure"""
    try:
        return np.asarray(dataset[()])
    except (OSError, ValueError, KeyError):
        database.unreadable.append(dataset.name or '')
        return None


def as_table(array: np.ndarray, columns: int) -> Optional[np.ndarray]:
    """Array as float64 table with the given number of columns, None for placeholders and other shapes"""
    if array.ndim != 2 or array.shape[1] != columns or array.dtype.kind not in 'fiu':
        return None
    return array.astype(np.float64)


def read_collision_pair(name: str, group: h5py.Group, database: Database) -> CollisionPair:
    """Collision pair group (current layout: /Cross-Sections/<pair>, legacy XSec layout: /<pair>)"""
    _, provenance = split_attributes(group.attrs, all_metadata=True)
    pair = CollisionPair(name=name, provenance=provenance)

    for member_name, member in group.items():
        if isinstance(member, h5py.Dataset):
            kind = XSecKind(member_name) if member_name in [k.value for k in XSEC_DATASET_KINDS] else XSecKind.UNKNOWN
            add_cross_section(pair, kind, member_name, None, member, database)
        elif isinstance(member, h5py.Group):
            kind = XSecKind(member_name) if member_name in [k.value for k in XSEC_GROUP_KINDS] else XSecKind.UNKNOWN
            if len(member) == 0:
                pair.empty_groups.append(member_name)
            for dataset_name, dataset in member.items():
                if isinstance(dataset, h5py.Dataset):
                    add_cross_section(pair, kind, dataset_name, member_name, dataset, database)
    return pair


def add_cross_section(pair: CollisionPair, kind: XSecKind, key: str, group: Optional[str], dataset: h5py.Dataset, database: Database) -> None:
    array = read_array(dataset, database)
    if array is None:
        return
    _, provenance = split_attributes(dataset.attrs, all_metadata=True)

    # Threshold: dataset name for excitations (as parsed by PICLas), otherwise the attribute written by create_xsec_db_lxcat.py
    threshold = parse_float(key) if kind in XSEC_THRESHOLD_KINDS or kind is XSecKind.UNKNOWN else None
    if threshold is None and 'Threshold [eV]' in provenance.extra:
        value = provenance.extra['Threshold [eV]']
        threshold = float(value) if isinstance(value, (int, float)) else parse_float(str(value))

    data = array.astype(np.float64) if array.dtype.kind in 'fiu' else np.empty((0, 2))
    pair.cross_sections.append(CrossSection(kind=kind, key=key, data=data, group=group, threshold=threshold, dtype=str(array.dtype), provenance=provenance))


# ----------------------------------------------------------------------------------------------------------------------------------
# Layouts
# ----------------------------------------------------------------------------------------------------------------------------------
def read_species_database(h5: h5py.File, database: Database) -> None:
    """Current layout (SpeciesDatabase.h5)"""
    for group_name, group in h5.items():
        for name in group.attrs:
            database.attributes[f'{group_name}@{name}'] = decode(group.attrs[name])

    for name, group in h5.get('Species', {}).items():
        attributes, provenance = split_attributes(group.attrs)
        species = Species(name=name, attributes=attributes, provenance=provenance)
        for dataset_name, dataset in group.items():
            array = read_array(dataset, database)
            if array is None:
                continue
            species.dtypes[dataset_name] = str(array.dtype)
            if dataset_name == 'ElectronicLevel':
                species.electronic_levels = as_table(array, 2)
                species.electronic_placeholder = species.electronic_levels is None
            elif dataset_name == 'VibrationalLevel':
                species.vibrational_levels = as_table(array, 1)
        database.species[name] = species

    for name, dataset in h5.get('Reactions', {}).items():
        attributes, provenance = split_attributes(dataset.attrs)
        database.reactions[name] = Reaction(name=name, attributes=attributes, provenance=provenance)

    for name, group in h5.get('Cross-Sections', {}).items():
        if isinstance(group, h5py.Group):
            database.collision_pairs[name] = read_collision_pair(name, group, database)

    for pair_name, pair in h5.get('Diffusion-Coefficients', {}).items():
        for source_name, source in pair.items():
            _, provenance = split_attributes(source.attrs, all_metadata=True)
            diffusion = DiffusionSet(pair=pair_name, database=source_name, provenance=provenance)
            for dataset_name, dataset in source.items():
                array = read_array(dataset, database)
                if array is not None:
                    diffusion.datasets[dataset_name] = array.astype(np.float64)
            database.diffusion.append(diffusion)

    for name, dataset in h5.get('Surface-Chemistry', {}).items():
        attributes, provenance = split_attributes(dataset.attrs)
        database.surface[name] = SurfaceEntry(name=name, data=read_array(dataset, database), attributes=attributes, provenance=provenance)


def read_legacy_xsec(h5: h5py.File, database: Database) -> None:
    """Legacy cross-section database: collision pairs directly in the root"""
    for name, group in h5.items():
        database.collision_pairs[name] = read_collision_pair(name, group, database)


def read_legacy_electronic(h5: h5py.File, database: Database) -> None:
    """Legacy electronic state database: one (N, 2) dataset per species directly in the root"""
    for name, dataset in h5.items():
        array = read_array(dataset, database)
        if array is None:
            continue
        _, provenance = split_attributes(dataset.attrs, all_metadata=True)
        levels = as_table(array, 2)
        database.species[name] = Species(name=name, electronic_levels=levels, electronic_placeholder=levels is None, provenance=provenance, dtypes={'ElectronicLevel': str(array.dtype)})


READERS = {
    Schema.SPECIES_DATABASE: read_species_database,
    Schema.LEGACY_XSEC: read_legacy_xsec,
    Schema.LEGACY_ELECTRONIC: read_legacy_electronic,
}


def read_database(path: Union[str, pathlib.Path]) -> Database:
    """Read a database file of any known layout into the data model"""
    path = pathlib.Path(path)
    if not path.is_file():
        raise DatabaseReadError(f'file not found: {path}')
    try:
        h5 = h5py.File(path, 'r')
    except OSError as e:
        raise DatabaseReadError(f'cannot open {path} as HDF5 file: {e}') from e

    with h5:
        schema = detect_schema(h5)
        database = Database(path=str(path), schema=schema)
        for name in h5.attrs:
            database.attributes[name] = decode(h5.attrs[name])
        reader = READERS.get(schema)
        if reader is not None:
            reader(h5, database)
    return database
