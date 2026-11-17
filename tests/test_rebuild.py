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
import yaml

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.guide import guide, spectrum
from piclas_db.piclas_db import main
from piclas_db.readers import read_database
from piclas_db.rebuild import derive, lxcat_database, lxcat_species
from piclas_db.resolve import Requirement
from piclas_db.store import Store
from tests.test_import import LXCAT, NIST_CSV
# ==================================================================================================================================
# Old files written like create_xsec_db_lxcat.py and convert-csv-to-hdf5.py did (synthetic data from the test downloads)

INFO_ELASTIC = "{'SPECIES': 'e / Ar', 'PROCESS': 'E + Ar -> E + Ar, Elastic', 'PARAM.': 'm/M = 0.00001, complete set'}"
INFO_IONIZATION = "{'SPECIES': 'e / Ar', 'PROCESS': 'E + Ar -> E + E + Ar+, Ionization', 'PARAM.': 'E = 15.7 eV, complete set'}"


@pytest.fixture
def store(tmp_path: pathlib.Path) -> Store:
    downloads = tmp_path / 'Downloads'
    downloads.mkdir()
    (downloads / 'argon.txt').write_text(LXCAT)
    assert main(['import', '--source-dir', str(downloads), '--store', str(tmp_path / 'store')]) == 0
    return Store(tmp_path / 'store')


@pytest.fixture
def old_file(tmp_path: pathlib.Path) -> pathlib.Path:
    path = tmp_path / 'LXCat_Database_old.h5'
    with h5py.File(path, 'w') as h5:
        elastic = h5.create_dataset('Ar-electron/ELASTIC', data=np.array([[0.0, 1.0e-20], [10.0, 2.0e-20]]))
        elastic.attrs['Info'] = INFO_ELASTIC
        elastic.attrs['Reference'] = 'Test-A database, www.lxcat.net, retrieved on June 1, 2025.'
        ionization = h5.create_dataset('Ar-electron/REACTION/electron-electron-ArIon1', data=np.array([[15.7, 0.0], [100.0, 3.0e-20]]))
        ionization.attrs['Info'] = INFO_IONIZATION  # no reference, as written by create_xsec_db_lxcat.py
        backscatter = h5.create_dataset('Ar-ArIon1/BACKSCATTER', data=np.array([[0.0, 1.0e-18], [1.0, 5.0e-19]], dtype=np.float32))
        backscatter.attrs['Reference'] = np.array([['Test-B database, www.lxcat.net, retrieved on February 17, 2025.']], dtype=object)
        h5.create_dataset('Ne-electron/ELASTIC', data=np.array([[0.0, 1.0e-20], [1.0, 2.0e-20]]))  # no provenance at all
    return path


def test_guide(capsys: pytest.CaptureFixture[str], tmp_path: pathlib.Path) -> None:
    lines = guide(Requirement.parse('lxcat/biagi-v7.1+phelps/ar'))
    assert any('Biagi-v7.1, Phelps' in line for line in lines)
    assert any('https://www.lxcat.net/Biagi-v7.1' in line for line in lines)
    assert any('Ar II' in line for line in guide(Requirement.parse('nist-asd/levels/arion1')))
    assert any('--custom gec' in line for line in guide(Requirement.parse('custom/gec')))
    assert [spectrum(name) for name in ('Ar', 'ArIon1', 'XeIon2', 'N2Ion1')] == ['Ar I', 'Ar II', 'Xe III', 'N2Ion1']

    assert main(['guide', 'lxcat/biagi-v7.1/xe']) == 0
    assert 'Xe' in capsys.readouterr().out
    assert main(['guide']) == 1
    assert main(['guide', 'nonsense']) == 1
    recipe = tmp_path / 'recipe.yaml'
    recipe.write_text('levels:\n  - source: nist-asd/levels/ar\n    species: Ar\n')
    assert main(['guide', '--recipe', str(recipe), '--store', str(tmp_path / 'store')]) == 0
    assert 'Ar I' in capsys.readouterr().out
    (tmp_path / 'Ar_I_levels.csv').write_text(NIST_CSV)
    main(['import', str(tmp_path / 'Ar_I_levels.csv'), '--store', str(tmp_path / 'store')])
    assert main(['guide', '--recipe', str(recipe), '--store', str(tmp_path / 'store')]) == 0
    assert 'nothing to download' in capsys.readouterr().out
    assert main(['guide', '--recipe', str(recipe), '--all', '--store', str(tmp_path / 'store')]) == 0


def test_provenance_parsing(old_file: pathlib.Path) -> None:
    database = read_database(old_file)
    elastic = database.collision_pairs['Ar-electron'].cross_sections[0]
    assert lxcat_database(elastic, None) == 'Test-A'
    assert lxcat_species(elastic, 'Ar-electron') == 'e / Ar'
    backscatter = database.collision_pairs['Ar-ArIon1'].cross_sections[0]
    assert lxcat_database(backscatter, None) == 'Test-B'
    assert lxcat_species(backscatter, 'Ar-ArIon1') == 'Ar^+ / Ar'
    assert lxcat_species(backscatter, 'Ar-electron') == 'e / Ar'  # without a header the pair name decides
    neon = database.collision_pairs['Ne-electron'].cross_sections[0]
    assert lxcat_database(neon, 'Parsed from xsec_collision.txt') is None


def test_derive(old_file: pathlib.Path, store: Store) -> None:
    derivation = derive(read_database(old_file), store)
    selections = {(selection.database, selection.species): selection for selection in derivation.recipe.cross_sections}
    assert set(selections) == {('Test-A', 'e / Ar'), ('Test-B', 'Ar^+ / Ar')}
    assert selections[('Test-A', 'e / Ar')].source.sha256 is not None  # pinned to the file found in the store
    assert derivation.unresolved == ['/Cross-Sections/Ne-electron/ELASTIC: no LXCat reference (no reference)']


def test_rebuild(old_file: pathlib.Path, store: Store, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / 'rebuilt.h5'
    assert main(['rebuild', str(old_file), '-o', str(output), '--store', str(store.root), '--offline']) == 0
    out = capsys.readouterr().out
    assert 'copied (not rebuilt)  /Cross-Sections/Ne-electron/ELASTIC' in out
    assert 'renamed' in out  # electron-electron-ArIon1 -> ArIon1-electron-electron
    recipe = yaml.safe_load(output.with_suffix('.recipe.yaml').read_text())
    assert len(recipe['cross_sections']) == 2
    assert main(['build', str(output.with_suffix('.recipe.yaml')), '-o', str(tmp_path / 'again.h5'), '--store', str(store.root), '--offline']) == 0
    rebuilt = read_database(output)
    assert set(rebuilt.collision_pairs) == {'Ar-electron', 'Ar-ArIon1', 'Ne-electron'}
    assert main(['rebuild', str(old_file), '-o', str(output), '--store', str(store.root), '--offline']) == 1  # exists


def test_rebuild_missing_and_nothing(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    old = tmp_path / 'xenon.h5'
    with h5py.File(old, 'w') as h5:
        elastic = h5.create_dataset('Xe-electron/ELASTIC', data=np.array([[0.0, 1.0e-19], [1.0, 2.0e-19]]))
        elastic.attrs['Reference'] = 'Biagi-v7.1 database, www.lxcat.net, retrieved on July 14, 2025.'
        elastic.attrs['Info'] = "{'SPECIES': 'e / Xe'}"
    assert main(['rebuild', str(old), '-o', str(tmp_path / 'x.h5'), '--store', str(tmp_path / 'store'), '--offline']) == 1
    out = capsys.readouterr().out
    assert 'lxcat/biagi-v7.1/xe' in out and 'Deselect all databases' in out

    levels = tmp_path / 'levels.h5'
    with h5py.File(levels, 'w') as h5:
        h5.create_dataset('Ar', data=np.array([[1.0, 0.0], [5.0, 134000.0]]))
    assert main(['rebuild', str(levels), '-o', str(tmp_path / 'l.h5'), '--store', str(tmp_path / 'store'), '--offline']) == 1
    assert 'Nothing in the file can be rebuilt' in capsys.readouterr().out
    assert main(['rebuild', str(levels), '-o', str(tmp_path / 'l.h5'), '--store', str(tmp_path / 'store'), '--offline', '--levels-from-nist']) == 1
    assert 'Ar I' in capsys.readouterr().out
    assert main(['rebuild', str(tmp_path / 'missing.h5'), '-o', str(tmp_path / 'm.h5')]) == 1
