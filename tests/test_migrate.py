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
from piclas_db.compare import compare
from piclas_db.migrate import migrate
from piclas_db.model import XSecKind
from piclas_db.piclas_db import main
from piclas_db.readers import DatabaseReadError, read_database
from piclas_db.schema import Schema
from piclas_db.tables import TablesError, export_tables
from piclas_db.writer import write_database
# ==================================================================================================================================
# Synthetic files with the quirks of existing databases: legacy layout, typos, float32, product order, 2D strings


@pytest.fixture
def species_file(tmp_path: pathlib.Path) -> pathlib.Path:
    path = tmp_path / 'SpeciesDatabase.h5'
    with h5py.File(path, 'w') as h5:
        ar = h5.create_group('Species/Ar')
        ar.attrs['MassIC'] = 6.63e-26
        ar.attrs['InteractionID'] = 1.0
        ar.attrs['* Reference'] = np.array([['HeatOfFormation', 'ATcT 1.130']], dtype=object)
        ar.create_dataset('ElectronicLevel', data=np.array([[1.0, 0.0], [3.0, 140000.0], [5.0, 134013.1]], dtype=np.float32))
        ion = h5.create_group('Species/ArIon1')
        ion.attrs['MassIC'] = 6.63e-26 - 9.1e-31
        ion.attrs['ChargeIC'] = 1.602176634e-19
        ion.attrs['InteractionID'] = 10
        ion.attrs['PreviousState'] = np.bytes_('Ar')
        ion.attrs['FullyIonized'] = False
        ion.attrs['alpha'] = 1.4
        electron = h5.create_group('Species/electron')
        electron.attrs['MassIC'] = 9.1e-31
        electron.attrs['InteractionID'] = 4
        electron.create_dataset('ElectronicLevel', data=np.array([0]))
        reaction = h5.create_dataset('Reactions/Ar+electron_ArIon1+electron+electron#1', data=0)
        reaction.attrs['Reactants'] = np.array([b'Ar', b'electron'], dtype='S255')
        reaction.attrs['Products'] = np.array([b'ArIon1', b'electron', b'electron'], dtype='S255')
        reaction.attrs['ChemistryModel'] = np.array([[b'Ar_Ionization', b'']], dtype='S255')
        reaction.attrs['ReactionModel'] = np.array([b'XSec'], dtype='S255')
        h5['Reactions'].attrs['AvailableChemistryModels,Reference'] = np.array([[b'Ar_Ionization', b'synthetic']], dtype='S255')
        h5['Cross-Sections/Ar-electron/ELASTIC'] = np.array([[0.0, 7.0e-20], [10.0, 1.0e-19]], dtype=np.float32)
        h5['Cross-Sections/Ar-electron/REACTION/ArIon1-electron-electron'] = np.array([[15.76, 0.0], [100.0, 2.8e-20]])
        h5['Diffusion-Coefficients/Ar-electron/Biagi/MOBILITY'] = np.array([[1.0, 2.0], [3.0, 4.0]])
        h5['Surface-Chemistry/StickingCoefficient'] = np.ones((2, 4))
    return path


@pytest.fixture
def legacy_file(tmp_path: pathlib.Path) -> pathlib.Path:
    path = tmp_path / 'XSec_Database_O2_O.h5'
    with h5py.File(path, 'w') as h5:
        h5['O-electron/ELASTIC'] = np.array([[0.0, 5.0e-20], [10.0, 6.0e-20]])
        h5['O-electron/ELECTRONIIC/1.97'] = np.array([[1.97, 0.0], [10.0, 1.0e-21]])
        h5['O-electron/REACTION/electron-electron-OIon1'] = np.array([[13.6, 0.0], [50.0, 1.0e-20]], dtype=np.float32)
        h5.create_group('O-electron/VIBRATION')
        h5['O2-electron/REACTION/O-electron-O'] = np.array([[8.4, 0.0], [20.0, 1.0e-21]])
        h5['O2-electron/REACTION/electron-O-O'] = np.array([[6.0, 0.0], [20.0, 2.0e-21]])
        h5['O2-electron/ELASTIC'] = np.array([[0.0, 5.0e-20], [10.0, 6.0e-20]])
        h5['O2-electron/ELASTIC'].attrs['Reference'] = np.array([['xsec_collision.txt']], dtype=object)
    return path


def test_writer_string_types(species_file: pathlib.Path, tmp_path: pathlib.Path) -> None:
    output = tmp_path / 'out.h5'
    write_database(read_database(species_file), output)
    with h5py.File(output, 'r') as h5:
        for name, attrs in (('Reactants', h5['Reactions/Ar+electron_ArIon1+electron+electron#1'].attrs), ('PreviousState', h5['Species/ArIon1'].attrs)):
            string_type = attrs.get_id(name).get_type()
            assert not string_type.is_variable_str()  # PICLas aborts on variable-length strings
            assert string_type.get_size() == 255
            assert string_type.get_strpad() == h5py.h5t.STR_NULLPAD  # PICLas aborts on null-terminated strings
        assert h5['Species/ArIon1'].attrs['FullyIonized'] == 0  # logicals are read as integers
        assert h5['Species/Ar/ElectronicLevel'].dtype == np.float64
        assert h5['Species/electron/ElectronicLevel'].shape == (1,)  # placeholder kept
        assert h5['Cross-Sections/Ar-electron/ELASTIC'].attrs['Type'] == b'ELASTIC'
        assert h5['Cross-Sections/Ar-electron/REACTION/ArIon1-electron-electron'].dtype == np.float64


@pytest.mark.parametrize('fixture', ['species_file', 'legacy_file'])
def test_round_trip(fixture: str, request: pytest.FixtureRequest, tmp_path: pathlib.Path) -> None:
    source = request.getfixturevalue(fixture)
    first, second = tmp_path / 'first.h5', tmp_path / 'second.h5'
    write_database(read_database(source), first)  # normalize once
    assert compare(read_database(source), read_database(first)).equal  # values unchanged by the normalization

    export_tables(read_database(first), tmp_path / 'tables')
    write_database(read_database(tmp_path / 'tables'), second)
    export_tables(read_database(second), tmp_path / 'tables2')

    # h5 -> tables -> h5 reproduces every value, attribute and dtype exactly
    with h5py.File(first, 'r') as a, h5py.File(second, 'r') as b:

        def same(name: str, obj: h5py.Group | h5py.Dataset) -> None:
            other = b[name]
            assert isinstance(other, (h5py.Group, h5py.Dataset))
            assert sorted(obj.attrs) == sorted(other.attrs), name
            for key in obj.attrs:
                assert np.array_equal(np.asarray(obj.attrs[key]), np.asarray(other.attrs[key])), f'{name}@{key}'
            if isinstance(obj, h5py.Dataset):
                assert isinstance(other, h5py.Dataset)
                assert obj.dtype == other.dtype and np.array_equal(obj[()], other[()]), name

        a.visititems(same)
    # and the tables are text-identical
    files = sorted(path.relative_to(tmp_path / 'tables') for path in (tmp_path / 'tables').rglob('*') if path.is_file())
    assert files == sorted(path.relative_to(tmp_path / 'tables2') for path in (tmp_path / 'tables2').rglob('*') if path.is_file())
    for file in files:
        assert (tmp_path / 'tables' / file).read_text() == (tmp_path / 'tables2' / file).read_text(), file


def test_tables_errors(species_file: pathlib.Path, tmp_path: pathlib.Path) -> None:
    export_tables(read_database(species_file), tmp_path / 'tables')
    with pytest.raises(TablesError):
        export_tables(read_database(species_file), tmp_path / 'tables')  # not empty
    (tmp_path / 'empty').mkdir()
    with pytest.raises(DatabaseReadError):
        read_database(tmp_path / 'empty')
    (tmp_path / 'tables' / 'database.yaml').write_text('format: something else\n')
    with pytest.raises(DatabaseReadError):
        read_database(tmp_path / 'tables')


def test_migrate_fixes(legacy_file: pathlib.Path, species_file: pathlib.Path) -> None:
    database = read_database(legacy_file)
    report = migrate(database)
    assert report.fixed == []  # without options the data PICLas reads stay the same
    assert any('moved from the root' in line for line in report.normalized)
    assert any('empty group' in line for line in report.normalized)

    database = read_database(legacy_file)
    report = migrate(database, fix=True, products=True)
    oxygen = database.collision_pairs['O-electron']
    assert oxygen.of_kind(XSecKind.ELECTRONIC)[0].group == 'ELECTRONIC'
    assert oxygen.of_kind(XSecKind.REACTION)[0].key == 'OIon1-electron-electron'
    assert len(report.skipped) == 2  # O-electron-O and electron-O-O are ambiguous and stay as they are
    assert {xsec.key for xsec in database.collision_pairs['O2-electron'].of_kind(XSecKind.REACTION)} == {'O-electron-O', 'electron-O-O'}

    species = read_database(species_file)
    report = migrate(species, fix=True)
    assert 'alphaVSS' in species.species['ArIon1'].attributes
    levels = species.species['Ar'].electronic_levels
    assert levels is not None
    assert np.all(np.diff(levels[:, 1]) >= 0.0)


def test_migrate_skips_collisions(tmp_path: pathlib.Path) -> None:
    path = tmp_path / 'collision.h5'
    with h5py.File(path, 'w') as h5:
        h5['O-electron/ELECTRONIIC/1.97'] = np.array([[1.97, 0.0], [10.0, 1.0e-21]])
        h5['O-electron/ELECTRONIC/1.97'] = np.array([[1.97, 0.0], [10.0, 2.0e-21]])
    report = migrate(read_database(path), fix=True)
    assert report.fixed == []
    assert len(report.skipped) == 1


def test_commands(legacy_file: pathlib.Path, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / 'migrated.h5'
    assert main(['migrate', str(legacy_file), '-o', str(output), '--fix']) == 0
    assert 'renamed to ELECTRONIC' in capsys.readouterr().out
    assert read_database(output).schema is Schema.SPECIES_DATABASE
    assert main(['migrate', str(legacy_file), '-o', str(output)]) == 1  # exists
    assert main(['migrate', str(output), '-o', str(output), '--force']) == 1  # input = output
    assert main(['migrate', str(tmp_path / 'missing.h5'), '-o', str(tmp_path / 'x.h5')]) == 1
    assert main(['export', str(output), '-o', str(tmp_path / 'tables')]) == 0
    assert main(['export', str(output), '-o', str(tmp_path / 'tables')]) == 1  # not empty
    assert main(['migrate', str(tmp_path / 'tables'), '-o', str(tmp_path / 'back.h5')]) == 0
    assert main(['diff', str(output), str(tmp_path / 'back.h5')]) == 0
