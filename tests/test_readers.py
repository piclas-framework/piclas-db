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
# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import pathlib

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import h5py
import numpy as np
import pytest

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.model import XSecKind
from piclas_db.readers import DatabaseReadError, decode, read_database
from piclas_db.schema import Schema
# ==================================================================================================================================
# Synthetic files that mimic the structure (and the quirks) of existing databases, no third-party data


@pytest.fixture
def species_database(tmp_path: pathlib.Path) -> pathlib.Path:
    path = tmp_path / 'SpeciesDatabase.h5'
    string = h5py.string_dtype()
    with h5py.File(path, 'w') as h5:
        ar = h5.create_group('Species/Ar')
        ar.attrs['MassIC'] = 6.63e-26
        ar.attrs['InteractionID'] = 1
        ar.attrs['* Reference'] = 'HeatOfFormation: ATcT 1.130'
        ar.create_dataset('ElectronicLevel', data=np.array([[1.0, 0.0], [5.0, 134013.1]]))
        fe = h5.create_group('Species/Fe')
        fe.attrs['alpha'] = 1.4  # wrong attribute name as in SpeciesDatabase.h5
        fe.create_dataset('ElectronicLevel', data=np.array([0]))  # placeholder
        reaction = h5.create_dataset('Reactions/Ar+electron_ArIon1+electron+electron#1', data=0)
        reaction.attrs.create('Reactants', np.array(['Ar', 'electron'], dtype=object), dtype=string)
        reaction.attrs.create('Products', np.array(['ArIon1', 'electron', 'electron'], dtype=object), dtype=string)
        reaction.attrs.create('ChemistryModel', np.array([['Ar_Ionization', '']], dtype=object), dtype=string)
        reaction.attrs.create('ReactionModel', np.array(['XSec'], dtype=object), dtype=string)
        h5['Reactions'].attrs['AvailableChemistryModels,Reference'] = 'synthetic'
        pair = h5.create_group('Cross-Sections/Ar-electron')
        pair.create_dataset('ELASTIC', data=np.array([[0.0, 7.0e-20], [10.0, 1.0e-19]], dtype=np.float32))
        pair.create_dataset('ELECTRONIC/11.5', data=np.array([[11.5, 0.0], [20.0, 1.0e-21]]))
        pair.create_dataset('REACTION/ArIon1-electron-electron', data=np.array([[15.76, 0.0], [100.0, 2.8e-20]]))
        h5.create_dataset('Diffusion-Coefficients/Ar-electron/Biagi/MOBILITY', data=np.ones((3, 2)))
        h5.create_dataset('Surface-Chemistry/StickingCoefficient', data=np.ones((2, 4)))
    return path


@pytest.fixture
def legacy_xsec(tmp_path: pathlib.Path) -> pathlib.Path:
    path = tmp_path / 'XSec_Database.h5'
    with h5py.File(path, 'w') as h5:
        h5.attrs['Info'] = 'First column is the collision energy in [eV], second column is the cross-section in [m^2]'
        pair = h5.create_group('O-electron')
        pair.create_dataset('ELASTIC', data=np.array([[0.0, 5.0e-20], [10.0, 6.0e-20]]))
        pair.create_dataset('ELECTRONIIC/1.97', data=np.array([[1.97, 0.0], [10.0, 1.0e-21]]))  # typo as in XSec_Database_O2_O.h5
        pair.create_group('VIBRATION')  # empty group
        ion = h5.create_group('Ar-ArIon1')
        backscatter = ion.create_dataset('BACKSCATTER', data=np.array([[0.1, 1.0e-18], [1.0, 8.0e-19]], dtype=np.float32))
        backscatter.attrs['Reference'] = np.array([['Phelps database, retrieved on 2025-02-17']], dtype=object)
        reaction = h5.create_dataset('Xe-electron/REACTION/electron-electron-XeIon1', data=np.array([[12.13, 0.0], [50.0, 3.0e-20]]))
        reaction.attrs['Threshold [eV]'] = 12.13
    return path


@pytest.fixture
def legacy_electronic(tmp_path: pathlib.Path) -> pathlib.Path:
    path = tmp_path / 'Electronic-State-Database.h5'
    with h5py.File(path, 'w') as h5:
        ar = h5.create_dataset('Ar', data=np.array([[1.0, 0.0], [5.0, 133982.9]]))
        ar.attrs['Reference'] = 'NIST ASD 5.8'
        h5.create_dataset('ArIon1', data=np.array([[4.0, 0.0], [2.0, 2059.3]]))
    return path


def test_read_species_database(species_database: pathlib.Path) -> None:
    db = read_database(species_database)
    assert db.schema is Schema.SPECIES_DATABASE
    assert db.summary() == {
        'species': 2,
        'electronic level sets': 1,
        'reactions': 1,
        'collision pairs': 1,
        'cross-sections': 3,
        'diffusion sets': 1,
        'surface entries': 1,
    }
    ar = db.species['Ar']
    assert ar.attributes == {'MassIC': 6.63e-26, 'InteractionID': 1}
    assert ar.provenance.reference == 'HeatOfFormation: ATcT 1.130'
    assert ar.electronic_levels is not None
    assert ar.electronic_levels.shape == (2, 2)
    # Unknown attributes are kept as physical attributes, placeholders are flagged
    assert 'alpha' in db.species['Fe'].attributes
    assert db.species['Fe'].electronic_placeholder
    reaction = db.reactions['Ar+electron_ArIon1+electron+electron#1']
    assert reaction.reactants == ['Ar', 'electron']
    assert reaction.products == ['ArIon1', 'electron', 'electron']
    pair = db.collision_pairs['Ar-electron']
    assert pair.of_kind(XSecKind.ELASTIC)[0].dtype == 'float32'
    assert pair.of_kind(XSecKind.ELASTIC)[0].data.dtype == np.float64
    assert pair.of_kind(XSecKind.ELECTRONIC)[0].threshold == pytest.approx(11.5)
    assert pair.of_kind(XSecKind.REACTION)[0].key == 'ArIon1-electron-electron'
    assert db.attributes['Reactions@AvailableChemistryModels,Reference'] == 'synthetic'


def test_read_legacy_xsec(legacy_xsec: pathlib.Path) -> None:
    db = read_database(legacy_xsec)
    assert db.schema is Schema.LEGACY_XSEC
    assert set(db.collision_pairs) == {'O-electron', 'Ar-ArIon1', 'Xe-electron'}
    oxygen = db.collision_pairs['O-electron']
    unknown = oxygen.of_kind(XSecKind.UNKNOWN)
    assert len(unknown) == 1
    assert unknown[0].group == 'ELECTRONIIC'
    assert unknown[0].threshold == pytest.approx(1.97)
    assert oxygen.empty_groups == ['VIBRATION']
    backscatter = db.collision_pairs['Ar-ArIon1'].of_kind(XSecKind.BACKSCATTER)[0]
    assert backscatter.provenance.reference == 'Phelps database, retrieved on 2025-02-17'
    reaction = db.collision_pairs['Xe-electron'].of_kind(XSecKind.REACTION)[0]
    assert reaction.threshold == pytest.approx(12.13)


def test_read_legacy_electronic(legacy_electronic: pathlib.Path) -> None:
    db = read_database(legacy_electronic)
    assert db.schema is Schema.LEGACY_ELECTRONIC
    assert set(db.species) == {'Ar', 'ArIon1'}
    assert db.species['Ar'].provenance.reference == 'NIST ASD 5.8'
    levels = db.species['ArIon1'].electronic_levels
    assert levels is not None
    assert levels[0, 0] == pytest.approx(4.0)


def test_read_errors(tmp_path: pathlib.Path) -> None:
    with pytest.raises(DatabaseReadError):
        read_database(tmp_path / 'missing.h5')
    path = tmp_path / 'text.h5'
    path.write_text('no HDF5')
    with pytest.raises(DatabaseReadError):
        read_database(path)


@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        (b'bytes', 'bytes'),
        (np.float64(1.5), 1.5),
        (np.array([3]), 3),
        (np.array([b'a', b'b']), ['a', 'b']),
        (np.array([['x', 'y']], dtype=object), [['x', 'y']]),
    ],
)
def test_decode(value: object, expected: object) -> None:
    assert decode(value) == expected
