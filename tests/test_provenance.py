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
import pytest

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db import provenance
from piclas_db.common.common_vars import Common
from piclas_db.piclas_db import main
from piclas_db.readers import read_database
from piclas_db.rules import run_checks
from piclas_db.store import Store
from tests.test_build import MOLECULE, RECIPE
from tests.test_import import LXCAT, NIST_CSV
# ==================================================================================================================================


@pytest.fixture
def store(tmp_path: pathlib.Path) -> Store:
    downloads = tmp_path / 'Downloads'
    downloads.mkdir()
    (downloads / 'argon.txt').write_text(LXCAT)
    (downloads / 'nitrogen.txt').write_text(MOLECULE)
    (downloads / 'Ar_I_levels.csv').write_text(NIST_CSV)
    assert main(['import', '--source-dir', str(downloads), '--store', str(tmp_path / 'store'), '--retrieved', '2026-11-17']) == 0
    return Store(tmp_path / 'store')


def test_build_writes_provenance(store: Store, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    recipe = tmp_path / 'recipe.yaml'
    recipe.write_text(RECIPE)
    output = tmp_path / 'database.h5'
    assert main(['build', str(recipe), '-o', str(output), '--store', str(store.root), '--offline']) == 0
    record = provenance.read(read_database(output).attributes)
    assert record.present
    assert record.version == Common().version
    assert record.format_version == provenance.FORMAT_VERSION
    assert record.command == f'build {recipe}'
    assert record.recipe == RECIPE
    assert record.recipe_intact
    checksums = {entry.meta['sha256'] for entry in store.entries()}
    assert set(record.source_checksums()) == checksums  # every original file used, identified by its sha256
    assert all('retrieved 2026-11-17' in line for line in record.sources)

    # the attributes are UTF-8 metadata that PICLas never reads; sources are a list of texts
    with h5py.File(output, 'r') as h5:
        assert h5py.check_string_dtype(h5.attrs.get_id('* piclas-db sources').dtype).length is None
        assert len(h5.attrs['* piclas-db sources']) == len(checksums)

    capsys.readouterr()
    assert main(['check', str(output)]) == 0
    out = capsys.readouterr().out
    assert f'piclas-db {Common().version}' in out and 'recipe embedded' in out


def test_migrate_and_rebuild_provenance(store: Store, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    recipe = tmp_path / 'recipe.yaml'
    recipe.write_text(RECIPE)
    built = tmp_path / 'built.h5'
    main(['build', str(recipe), '-o', str(built), '--store', str(store.root), '--offline'])

    migrated = tmp_path / 'migrated.h5'
    assert main(['migrate', str(built), '-o', str(migrated), '--fix']) == 0
    record = provenance.read(read_database(migrated).attributes)
    assert record.command == f'migrate {built} --fix'
    assert record.input is not None and provenance.file_sha256(built) in record.input
    assert record.recipe is None  # replaced, the built file keeps its own provenance

    capsys.readouterr()
    rebuilt = tmp_path / 'rebuilt.h5'
    assert main(['rebuild', str(built), '-o', str(rebuilt), '--store', str(store.root), '--offline']) == 0
    out = capsys.readouterr().out
    assert 'Recipe embedded in' in out  # the exact recipe of the build is used, nothing derived
    assert '0 identical' not in out
    record = provenance.read(read_database(rebuilt).attributes)
    assert record.recipe == RECIPE
    assert record.command == f'rebuild {built}'


def test_findings(tmp_path: pathlib.Path) -> None:
    path = tmp_path / 'database.h5'
    with h5py.File(path, 'w') as h5:
        group = h5.create_group('Species/Ar')
        group.attrs['MassIC'] = 6.63e-26
        group.attrs['InteractionID'] = 1
        group.attrs['* Reference'] = 'synthetic'
    assert [finding.rule for finding in run_checks(read_database(path))] == ['provenance-file']
    with h5py.File(path, 'a') as h5:
        for name, value in provenance.create('build test.yaml', recipe_text='levels: []\n').items():
            h5.attrs[name] = value
        h5.attrs['* piclas-db recipe'] = 'levels: [changed]\n'
        h5.attrs['* piclas-db format version'] = provenance.FORMAT_VERSION + 1
    assert sorted(finding.rule for finding in run_checks(read_database(path))) == ['provenance-format', 'provenance-recipe']
