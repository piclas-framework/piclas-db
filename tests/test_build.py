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
import numpy as np
import pytest

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.build import BuildError, build, piclas_name, products
from piclas_db.model import XSecKind
from piclas_db.piclas_db import main
from piclas_db.readers import read_database
from piclas_db.recipe import RecipeError, load_recipe
from piclas_db.reference import CM_TO_K
from piclas_db.resolve import resolve
from piclas_db.rules import Severity, run_checks
from piclas_db.store import Store
from tests.test_import import LXCAT, NIST_CSV
# ==================================================================================================================================
# Synthetic LXCat file with molecular processes (invented numbers, structure of an LXCat download)

MOLECULE = """LXCat, www.lxcat.net
Generated on 02 Jun 2026. All rights reserved.

RECOMMENDED REFERENCE FORMAT
- Test-M database, www.lxcat.net, retrieved on June 2, 2026.

xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
DATABASE:         Test-M database
PERMLINK:         www.lxcat.net/Test-M
xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
""" + ''.join(
    f"""
{keyword}
N2
 {param}
SPECIES: e / N2
PROCESS: {process}
PARAM.:  {parameters}
COLUMNS: Energy (eV) | Cross section (m2)
-----------------------------
 {start}\t0.0
 1.0e+2\t1.0e-20
-----------------------------
"""
    for keyword, param, process, parameters, start in (
        ('EFFECTIVE', '1.9e-5', 'E + N2 -> E + N2, Effective', 'm/M = 0.0000196', '0.0'),
        ('EXCITATION', '0.02', 'E + N2 -> E + N2(rot), Excitation', 'E = 0.02 eV', '0.02'),
        ('EXCITATION', '0.29', 'E + N2 -> E + N2(v=1), Excitation', 'E = 0.29 eV', '0.29'),
        ('EXCITATION', '6.17', 'E + N2 -> E + N2(A3), Excitation', 'E = 6.17 eV', '6.17'),
        ('IONIZATION', '15.6', 'E + N2 -> E + E + N2+, Ionization', 'E = 15.6 eV', '15.6'),
        ('IONIZATION', '24.3', 'E + N2 -> E + E + N + N+, Ionization', 'E = 24.3 eV', '24.3'),
        ('ATTACHMENT', '', 'E + N2 -> N2-, Attachment', '', '0.0'),
    )
)


@pytest.fixture
def store(tmp_path: pathlib.Path) -> Store:
    downloads = tmp_path / 'Downloads'
    downloads.mkdir()
    (downloads / 'argon.txt').write_text(LXCAT)
    (downloads / 'nitrogen.txt').write_text(MOLECULE)
    (downloads / 'Ar_I_levels.csv').write_text(NIST_CSV)
    assert main(['import', '--source-dir', str(downloads), '--store', str(tmp_path / 'store'), '--retrieved', '2026-11-17']) == 0
    return Store(tmp_path / 'store')


def write_recipe(tmp_path: pathlib.Path, text: str) -> pathlib.Path:
    path = tmp_path / 'recipe.yaml'
    path.write_text(text)
    return path


RECIPE = """
cross_sections:
  - source: lxcat/test-a+test-b/ar
    database: Test-A
    species: e / Ar
  - source: lxcat/test-a+test-b/ar
    species: Ar^+ / Ar
  - source: lxcat/test-m/n2
    species: e / N2
levels:
  - source: nist-asd/levels/ar
    species: Ar
species:
  Ar: {MassIC: 6.63e-26, InteractionID: 1}
  ArIon1: {MassIC: 6.6299e-26, ChargeIC: 1.602176634e-19, InteractionID: 10}
  electron: {MassIC: 9.1e-31, ChargeIC: -1.602176634e-19, InteractionID: 4}
reactions:
  'Ar+electron_ArIon1+electron+electron#1': {Reactants: [Ar, electron], Products: [ArIon1, electron, electron], ReactionModel: XSec, ChemistryModel: [[Ar_Ionization, '']]}
"""


def test_names() -> None:
    assert [piclas_name(name) for name in ('E', 'Ar+', 'Ar^+', 'Ar++', 'Ar^2+', 'Xe+2', 'N2+', 'Ar*', 'Ar(1S5)', 'Ar*(11.55eV)')] == [
        'electron',
        'ArIon1',
        'ArIon1',
        'ArIon2',
        'ArIon2',
        'XeIon2',
        'N2Ion1',
        'Ar',
        'Ar',
        'Ar',
    ]
    assert products('E + Ar -> E + E + Ar+, Ionization') == ['ArIon1', 'electron', 'electron']
    assert products('E + N2 -> E + E + N + N+, Ionization') == ['N', 'NIon1', 'electron', 'electron']


def test_build(store: Store, tmp_path: pathlib.Path) -> None:
    recipe = load_recipe(write_recipe(tmp_path, RECIPE))
    database, report = build(recipe, resolve(store, recipe.requirements))
    argon = database.collision_pairs['Ar-electron']
    assert [xsec.kind for xsec in argon.cross_sections] == [XSecKind.ELASTIC, XSecKind.REACTION]
    assert argon.cross_sections[1].key == 'ArIon1-electron-electron'
    assert argon.cross_sections[1].threshold == pytest.approx(15.7)
    assert argon.cross_sections[0].provenance.reference == 'Test-A database, www.lxcat.net, retrieved on June 1, 2026.'
    assert 'sha256' in str(argon.cross_sections[0].provenance.extra['* Source'])
    assert [xsec.kind for xsec in database.collision_pairs['Ar-ArIon1'].cross_sections] == [XSecKind.BACKSCATTER]

    nitrogen = {(xsec.group, xsec.key) for xsec in database.collision_pairs['N2-electron'].cross_sections}
    assert nitrogen == {
        (None, 'EFFECTIVE'),
        ('ROTATION', '0.02'),
        ('VIBRATION', '0.29'),
        ('ELECTRONIC', '6.17'),
        ('REACTION', 'N2Ion1-electron-electron'),
        ('REACTION', 'N-NIon1-electron-electron'),
    }
    assert any('ATTACHMENT not supported' in note for note in report.notes)

    levels = database.species['Ar'].electronic_levels
    assert levels is not None
    assert levels[1, 1] == pytest.approx(93000.0 * CM_TO_K)
    assert database.species['Ar'].attributes['MassIC'] == pytest.approx(6.63e-26)
    assert 'Ar+electron_ArIon1+electron+electron#1' in database.reactions


def test_build_command(store: Store, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    recipe = write_recipe(tmp_path, RECIPE)
    output = tmp_path / 'database.h5'
    assert main(['build', str(recipe), '-o', str(output), '--store', str(store.root), '--offline']) == 0
    assert main(['build', str(recipe), '-o', str(output), '--store', str(store.root)]) == 1  # exists
    assert main(['build', str(recipe), '-o', str(output), '--store', str(store.root), '--force']) == 0
    database = read_database(output)
    assert database.summary()['cross-sections'] == 9
    errors = [finding for finding in run_checks(database) if finding.severity is Severity.ERROR]
    assert errors == []
    # the output is the same as the original data
    data = database.collision_pairs['Ar-electron'].of_kind(XSecKind.ELASTIC)[0].data
    assert np.array_equal(data, [[0.0, 1.0e-20], [10.0, 2.0e-20]])

    missing = write_recipe(tmp_path, 'cross_sections:\n  - source: lxcat/biagi-v7.1/xe\n    species: e / Xe\n')
    assert main(['build', str(missing), '-o', str(tmp_path / 'x.h5'), '--store', str(store.root)]) == 1
    assert 'missing' in capsys.readouterr().out


@pytest.mark.parametrize(
    ('text', 'message'),
    [
        ('cross_sections:\n  - species: e / Ar\n', 'source'),
        ('cross_sections:\n  - source: lxcat/x/y\n', 'species'),
        ('cross_sections:\n  - source: lxcat/x/y\n    species: e / Ar\n    types: {Isotropic: ELASTICC}\n', 'unknown kind'),
        ('levels:\n  - source: nist-asd/levels/ar\n', 'species'),
        ('species: [Ar]\n', 'mapping'),
        ('molecules: {}\n', 'unknown sections'),
        ('- a list\n', 'mapping'),
        (':\n  - [\n', 'cannot read'),
    ],
)
def test_recipe_errors(tmp_path: pathlib.Path, text: str, message: str) -> None:
    with pytest.raises(RecipeError, match=message):
        load_recipe(write_recipe(tmp_path, text))


def test_selection_errors(store: Store, tmp_path: pathlib.Path) -> None:
    for text, message in (
        ('cross_sections:\n  - source: lxcat/test-a+test-b/ar\n    species: e / Xe\n', 'no data'),
        ('cross_sections:\n  - source: lxcat/test-a+test-b/ar\n    database: Test-B\n    species: e / Ar\n', 'no data'),
    ):
        recipe = load_recipe(write_recipe(tmp_path, text))
        with pytest.raises(BuildError, match=message):
            build(recipe, resolve(store, recipe.requirements))
    selected = load_recipe(write_recipe(tmp_path, 'cross_sections:\n  - source: lxcat/test-m/n2\n    species: e / N2\n    processes: [Effective]\n    pair: N2-electron\n'))
    database, _ = build(selected, resolve(store, selected.requirements))
    assert len(database.collision_pairs['N2-electron'].cross_sections) == 1
