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
"""Writer for the current PICLas database layout (docs/layout.md)

Strings read by PICLas are written as fixed-length, null-padded ASCII strings of 255 characters: PICLas aborts on variable-length
and null-terminated strings (ReadAttribute in hdf5_input.f90). Metadata strings that PICLas never reads are variable-length UTF-8.
All numerical data are written as float64.
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import pathlib
from typing import Union

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import h5py
import numpy as np

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.model import AttrValue, Database, Provenance
# ==================================================================================================================================

STRING_LENGTH = 255  # CHARACTER(LEN=255) in PICLas
REGENERATED = ('Type', 'Threshold [eV]')  # cross-section attributes written from the data model, not copied


def fixed_strings(value: AttrValue) -> np.ndarray:
    """String or (nested) list of strings as fixed-length ASCII array readable by PICLas"""
    encoded = np.vectorize(lambda text: str(text).encode('ascii', errors='replace'), otypes=[object])(np.array(value, dtype=object))
    return encoded.astype(f'S{STRING_LENGTH}')


def write_attribute(attrs: h5py.AttributeManager, name: str, value: AttrValue, metadata: bool = False) -> None:
    """Write one attribute with the type PICLas expects"""
    if value is None:
        return
    if isinstance(value, (bool, np.bool_)):
        attrs[name] = np.int64(int(value))  # PICLas reads logicals as integers
    elif isinstance(value, int):
        attrs[name] = np.int64(value)
    elif isinstance(value, float):
        attrs[name] = np.float64(value)
    elif isinstance(value, str) or (isinstance(value, list) and value and isinstance(np.ravel(np.array(value, dtype=object))[0], str)):
        if metadata:
            text = value if isinstance(value, str) else ' '.join(str(item) for item in np.ravel(np.array(value, dtype=object)))
            attrs.create(name, text, dtype=h5py.string_dtype('utf-8'))
        else:
            attrs.create(name, fixed_strings(value))  # keeps the fixed length also for scalars
    elif isinstance(value, (list, np.ndarray)):
        array = np.asarray(value)
        attrs[name] = array.astype(np.float64) if array.dtype.kind == 'f' else array
    else:
        attrs.create(name, str(value), dtype=h5py.string_dtype('utf-8'))


def write_attributes(attrs: h5py.AttributeManager, attributes: dict[str, AttrValue]) -> None:
    for name, value in attributes.items():
        write_attribute(attrs, name, value, metadata=name.startswith('* '))


def write_provenance(attrs: h5py.AttributeManager, provenance: Provenance, reference_name: str = 'Reference', skip: tuple[str, ...] = ()) -> None:
    if provenance.reference is not None:
        write_attribute(attrs, reference_name, provenance.reference, metadata=True)
    if provenance.info is not None:
        write_attribute(attrs, 'Info', provenance.info, metadata=True)
    for name, value in provenance.extra.items():
        if name not in skip:
            write_attribute(attrs, name, value, metadata=True)


def write_database(database: Database, path: Union[str, pathlib.Path]) -> None:
    """Write the data model in the current layout (always a new file)"""
    with h5py.File(path, 'w') as h5:
        for key, value in database.attributes.items():
            group_name, _, name = key.rpartition('@')
            target = h5.require_group(group_name).attrs if group_name else h5.attrs
            write_attribute(target, name, value, metadata=name.startswith('* ') or not group_name)

        for species in database.species.values():
            group = h5.require_group(f'Species/{species.name}')
            write_attributes(group.attrs, species.attributes)
            write_provenance(group.attrs, species.provenance, reference_name='* Reference')
            if species.electronic_levels is not None:
                group.create_dataset('ElectronicLevel', data=species.electronic_levels.astype(np.float64))
            elif species.electronic_placeholder:
                group.create_dataset('ElectronicLevel', data=np.array([0], dtype=np.int64))
            if species.vibrational_levels is not None:
                group.create_dataset('VibrationalLevel', data=species.vibrational_levels.astype(np.float64))

        for reaction in database.reactions.values():
            dataset = h5.require_group('Reactions').create_dataset(reaction.name, data=np.int64(0))
            write_attributes(dataset.attrs, reaction.attributes)
            write_provenance(dataset.attrs, reaction.provenance, reference_name='* Reference')

        for pair in database.collision_pairs.values():
            group = h5.require_group(f'Cross-Sections/{pair.name}')
            write_provenance(group.attrs, pair.provenance)
            for xsec in pair.cross_sections:
                parent = group.require_group(xsec.group) if xsec.group else group
                dataset = parent.create_dataset(xsec.key, data=xsec.data.astype(np.float64))
                dataset.attrs.create('Type', fixed_strings(xsec.kind.value))
                if xsec.threshold is not None:
                    dataset.attrs['Threshold [eV]'] = np.float64(xsec.threshold)
                write_provenance(dataset.attrs, xsec.provenance, skip=REGENERATED)

        for diffusion in database.diffusion:
            group = h5.require_group(f'Diffusion-Coefficients/{diffusion.pair}/{diffusion.database}')
            write_provenance(group.attrs, diffusion.provenance)
            for name, data in diffusion.datasets.items():
                group.create_dataset(name, data=data.astype(np.float64))

        for entry in database.surface.values():
            data = entry.data if entry.data is not None else np.int64(0)
            dataset = h5.require_group('Surface-Chemistry').create_dataset(entry.name, data=data)
            write_attributes(dataset.attrs, entry.attributes)
            write_provenance(dataset.attrs, entry.provenance)
