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
import pytest

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.piclas_db import main
from piclas_db.readers import read_database
from piclas_db.recipe import RecipeError, load_recipe
from piclas_db.sources.identify import IdentifyError, identify
from piclas_db.store import Store
# ==================================================================================================================================

OWN = """format: piclas-db own data
format_version: 1
name: PICLas parameters
description: test values (invented)
species:
  Ar: {Tref: 273, dref: 4.0e-10, omega: 0.31, alphaVSS: 1.4, InteractionID: 1, MassIC: 6.6e-26, Reference: "Book 1994, Table A1"}
  N2: {Tref: 273, dref: 4.1e-10, omega: 0.24, InteractionID: 2, CharaTempVib: 3393.3, Reference: "Book 1994; Tables 1979"}
"""


def test_own_data_file(tmp_path: pathlib.Path) -> None:
    path = tmp_path / 'own.yaml'
    path.write_text(OWN)
    identified = identify(path)
    assert (identified.provider, identified.kind, identified.dataset) == ('own', 'species-parameters', 'piclas-parameters')
    assert identified.species == ['Ar', 'N2']
    for text, message in (
        (OWN.replace('  N2: {Tref: 273, dref: 4.1e-10, omega: 0.24, InteractionID: 2, CharaTempVib: 3393.3, Reference: "Book 1994; Tables 1979"}', '  N2: {Tref: 273}'), 'N2: "Reference" missing'),
        (OWN.replace('name: PICLas parameters\n', ''), '"name" required'),
        (OWN.replace('format_version: 1', 'format_version: 9'), 'newer'),
        ('format: piclas-db own data\nname: x\nspecies: {}\n', 'at least one species'),
        ('format: piclas-db own data\n  : [', 'YAML'),
    ):
        path.write_text(text)
        with pytest.raises(IdentifyError, match=message):
            identify(path)


def test_build_with_own_data(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = tmp_path / 'store'
    (tmp_path / 'own.yaml').write_text(OWN)
    assert main(['import', str(tmp_path / 'own.yaml'), '--store', str(store)]) == 0
    assert Store(store).entries()[0].meta['imported_by'] == 'piclas-db test <test@example.com>'
    recipe = tmp_path / 'recipe.yaml'
    recipe.write_text('own_data: own/piclas-parameters\nspecies:\n  Ar: {}\n  N2: {omega: 0.25}\n  O2: {}\n')
    output = tmp_path / 'database.h5'
    capsys.readouterr()
    assert main(['build', str(recipe), '-o', str(output), '--store', str(store), '--offline']) == 0
    out = capsys.readouterr().out
    assert 'N2: omega written in the recipe, not in the store' in out and 'O2: not in the own data' in out
    database = read_database(output)
    ar, n2 = database.species['Ar'], database.species['N2']
    assert ar.attributes['alphaVSS'] == pytest.approx(1.4) and ar.attributes['InteractionID'] == 1
    assert n2.attributes['omega'] == pytest.approx(0.25)  # the recipe takes precedence
    assert n2.attributes['CharaTempVib'] == pytest.approx(3393.3)
    assert ar.provenance.reference == 'Book 1994, Table A1' and 'own/piclas-parameters' in str(ar.provenance.extra['* Source'])
    assert 'Reference' not in ar.attributes  # the reference is provenance, not a PICLas attribute

    for text, message in (('own_data: lxcat/x/y\n', 'own/<name>'), ('own_data: [nothing]\n', 'provider')):
        recipe.write_text(text)
        with pytest.raises(RecipeError, match=message):
            load_recipe(recipe)
    recipe.write_text('own_data: own/missing\nspecies:\n  Ar: {}\n')
    assert main(['build', str(recipe), '-o', str(output), '--store', str(store), '--offline', '--force']) == 1  # not in the store
