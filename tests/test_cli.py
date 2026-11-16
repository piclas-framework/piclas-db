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
from piclas_db.common.common_vars import Common
from piclas_db.piclas_db import main
from piclas_db.schema import Schema, detect_schema
# ==================================================================================================================================
# All test data is synthetic and created on the fly: no third-party data in this repository


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(['--version'])
    assert exit_info.value.code == 0
    assert Common().version in capsys.readouterr().out


def test_help_without_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert 'check' in capsys.readouterr().out


def test_planned_command_returns_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(['build', '-o', 'database.h5']) == 1
    assert 'not implemented yet' in capsys.readouterr().out


def make_species_database(path: pathlib.Path) -> None:
    with h5py.File(path, 'w') as h5:
        species = h5.create_group('Species/Ar')
        species.attrs['MassIC'] = 6.63e-26
        species.create_dataset('ElectronicLevel', data=np.array([[1.0, 0.0], [5.0, 134008.74]]))
        h5.create_dataset('Cross-Sections/Ar-electron/ELASTIC', data=np.array([[0.0, 7.0e-20], [1.0, 1.4e-20]]))


def make_legacy_xsec(path: pathlib.Path) -> None:
    with h5py.File(path, 'w') as h5:
        h5.create_dataset('Ar-electron/ELASTIC', data=np.array([[0.0, 7.0e-20], [1.0, 1.4e-20]]))


def make_legacy_electronic(path: pathlib.Path) -> None:
    with h5py.File(path, 'w') as h5:
        h5.create_dataset('Ar', data=np.array([[1.0, 0.0], [5.0, 134008.74]]))


@pytest.mark.parametrize(
    ('factory', 'schema'),
    [
        (make_species_database, Schema.SPECIES_DATABASE),
        (make_legacy_xsec, Schema.LEGACY_XSEC),
        (make_legacy_electronic, Schema.LEGACY_ELECTRONIC),
    ],
)
def test_detect_schema(tmp_path: pathlib.Path, factory, schema: Schema) -> None:
    path = tmp_path / 'database.h5'
    factory(path)
    with h5py.File(path, 'r') as h5:
        assert detect_schema(h5) is schema
    assert main(['check', str(path)]) == 0


def test_check_missing_file(tmp_path: pathlib.Path) -> None:
    assert main(['check', str(tmp_path / 'missing.h5')]) == 1


def test_check_no_hdf5_file(tmp_path: pathlib.Path) -> None:
    path = tmp_path / 'database.h5'
    path.write_text('not an HDF5 file')
    assert main(['check', str(path)]) == 1
