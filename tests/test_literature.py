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
from piclas_db.literature import AREA_UNITS, ENERGY_UNITS, LiteratureError, read_raw, unit_factor
from piclas_db.piclas_db import main
from piclas_db.readers import read_database
from piclas_db.recipe import RecipeError, load_recipe
from piclas_db.rules import run_checks
from piclas_db.store import Store
# ==================================================================================================================================
# Synthetic paper (a minimal PDF) and invented table values; no content of real papers

PDF = b'%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n'
ROWS = '16,0.03\n20,0.28\n50,0.91\n100,0.90\n'
RECIPE = """literature:
  - source: literature/test-2008/total-ionization
    pair: H2-electron
    kind: REACTION
    key: H2Ion1-electron-electron
"""


@pytest.fixture
def store(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> Store:
    monkeypatch.setenv('PICLAS_DB_STORE', str(tmp_path / 'store'))
    (tmp_path / 'paper.pdf').write_bytes(PDF)
    assert main(['import', str(tmp_path / 'paper.pdf'), '--literature', 'Test 2008', '--doi', '10.0000/test', '--reference', 'A. Author, J. Test 1, 1 (2008)']) == 0
    return Store(tmp_path / 'store')


def entered(tmp_path: pathlib.Path, rows: str = ROWS, unit: str = '1e-16 cm^2') -> pathlib.Path:
    """Template filled in as a person would do it"""
    assert main(['literature', 'template', 'test-2008', 'total-ionization', '--page', '14 (926)', '--table', '12', '-o', str(tmp_path / 'work')]) == 0
    record_file = tmp_path / 'work' / 'total-ionization.extraction.yaml'
    (tmp_path / 'work' / 'total-ionization.csv').write_text((tmp_path / 'work' / 'total-ionization.csv').read_text() + rows)
    record = yaml.safe_load(record_file.read_text())
    record['created']['by'] = 'tester'
    record['columns']['cross_section']['unit'] = unit
    record_file.write_text(yaml.safe_dump(record))
    return record_file


def test_units() -> None:
    assert unit_factor('eV', ENERGY_UNITS) == pytest.approx(1.0)
    assert unit_factor('keV', ENERGY_UNITS) == pytest.approx(1.0e3)
    assert unit_factor('1e-16 cm^2', AREA_UNITS) == pytest.approx(1.0e-20)
    assert unit_factor('10^-17 cm2', AREA_UNITS) == pytest.approx(1.0e-21)
    assert unit_factor('A^2', AREA_UNITS) == pytest.approx(1.0e-20)
    with pytest.raises(LiteratureError):
        unit_factor('barn', AREA_UNITS)


def test_read_raw() -> None:
    table = read_raw('# comment\nenergy,cross_section,uncertainty\n1,2,0.1\n3,4,0.2\n')
    assert table.energy.tolist() == [1.0, 3.0] and table.uncertainty is not None
    with pytest.raises(LiteratureError):
        read_raw('energy,cross_section\n1,x\n2,3\n')
    with pytest.raises(LiteratureError):
        read_raw('energy,cross_section\n1,2\n')


def test_import_template_add_review_build(store: Store, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    paper = next(entry for entry in store.entries() if entry.meta['provider'] == 'literature')
    assert (paper.meta['dataset'], paper.meta['doi']) == ('test-2008', '10.0000/test')
    assert paper.path.read_bytes() == PDF

    assert main(['literature', 'add', str(entered(tmp_path))]) == 0
    assert 'review pending' in capsys.readouterr().out
    recipe = tmp_path / 'recipe.yaml'
    recipe.write_text(RECIPE)
    output = tmp_path / 'database.h5'
    assert main(['build', str(recipe), '-o', str(output), '--offline']) == 1  # not reviewed
    assert main(['build', str(recipe), '-o', str(output), '--offline', '--allow-unreviewed']) == 0
    assert 'literature-unreviewed' in [finding.rule for finding in run_checks(read_database(output))]

    assert main(['literature', 'review', 'test-2008/total-ionization', '--approve', '--reviewer', 'reviewer']) == 0
    assert main(['build', str(recipe), '-o', str(output), '--offline', '--force']) == 0
    database = read_database(output)
    assert 'literature-unreviewed' not in [finding.rule for finding in run_checks(database)]
    xsec = database.collision_pairs['H2-electron'].cross_sections[0]
    assert xsec.key == 'H2Ion1-electron-electron'
    assert np.allclose(xsec.data, [[16.0, 0.03e-20], [20.0, 0.28e-20], [50.0, 0.91e-20], [100.0, 0.90e-20]])  # converted to m^2
    assert 'doi:10.0000/test' in str(xsec.provenance.reference) and 'table 12' in str(xsec.provenance.reference)
    assert str(xsec.provenance.extra['* Review']).startswith('approved by reviewer')
    with h5py.File(output, 'r') as h5:
        assert '* Extraction' in h5['Cross-Sections/H2-electron/REACTION/H2Ion1-electron-electron'].attrs

    capsys.readouterr()
    assert main(['literature', 'list']) == 0
    out = capsys.readouterr().out
    assert 'test-2008/total-ionization@' in out and 'review approved' in out
    assert main(['literature', 'review', 'test-2008/total-ionization', '--reject', '--reviewer', 'reviewer']) == 0
    assert main(['build', str(recipe), '-o', str(output), '--offline', '--force', '--allow-unreviewed']) == 1  # rejected: never used


def test_add_errors(store: Store, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    record = entered(tmp_path, rows='16,0.03\n20,0.28\n18,0.5\n')
    assert main(['literature', 'add', str(record)]) == 1
    assert 'energies not increasing' in capsys.readouterr().out
    data = record.parent / 'total-ionization.csv'
    data.write_text('energy,cross_section\n16,0.03\n20,0.28\n')
    content = yaml.safe_load(record.read_text())
    content['source']['file_sha256'] = '0' * 64
    content['columns']['cross_section']['unit'] = 'barn'
    record.write_text(yaml.safe_dump(content))
    assert main(['literature', 'add', str(record)]) == 1
    out = capsys.readouterr().out
    assert 'does not match' in out and 'unknown unit' in out
    assert main(['literature', 'template', 'unknown', 'x']) == 1
    assert main(['literature', 'template', 'test-2008', 'total-ionization', '-o', str(tmp_path / 'work')]) == 1  # exists
    assert main(['literature', 'review', 'test-2008/missing', '--approve', '--reviewer', 'r']) == 1
    assert main(['literature', 'review', 'test-2008/total-ionization', '--reviewer', 'r']) == 1  # neither approve nor reject
    assert main(['literature', 'add']) == 1
    (tmp_path / 'notes.txt').write_text('x')
    assert main(['import', str(tmp_path / 'notes.txt'), '--literature', 'x', '--doi', '1']) == 1  # not a PDF
    assert main(['import', str(tmp_path / 'paper.pdf'), '--literature', 'x']) == 1  # citation missing


def test_recipe_errors(tmp_path: pathlib.Path) -> None:
    for text, message in (
        ('literature:\n  - source: literature/a/b\n    kind: REACTION\n', 'pair'),
        ('literature:\n  - source: literature/a/b\n    pair: H2-electron\n    kind: REACTION\n', 'key'),
        ('literature:\n  - source: literature/a/b\n    pair: H2-electron\n    kind: ELECTRONIC\n', 'threshold'),
        ('literature:\n  - source: lxcat/a/b\n    pair: H2-electron\n    kind: ELASTIC\n', 'literature/'),
    ):
        path = tmp_path / 'recipe.yaml'
        path.write_text(text)
        with pytest.raises(RecipeError, match=message):
            load_recipe(path)


def add_rows(tmp_path: pathlib.Path, name: str, rows: str) -> pathlib.Path:
    """A second extraction of the test paper with other values"""
    assert main(['literature', 'template', 'test-2008', name, '--page', '15', '--table', '13', '-o', str(tmp_path / 'work')]) == 0
    record_file = tmp_path / 'work' / f'{name}.extraction.yaml'
    (tmp_path / 'work' / f'{name}.csv').write_text((tmp_path / 'work' / f'{name}.csv').read_text() + rows)
    record = yaml.safe_load(record_file.read_text())
    record['created']['by'] = 'tester'
    record_file.write_text(yaml.safe_dump(record))
    return record_file


def test_combined_parts(store: Store, tmp_path: pathlib.Path) -> None:
    assert main(['literature', 'add', str(entered(tmp_path))]) == 0  # total-ionization: 16, 20, 50, 100 eV
    assert main(['literature', 'add', str(add_rows(tmp_path, 'partial', '30,0.60\n50,0.80\n100,0.85\n1000,0.20\n'))]) == 0
    recipe = tmp_path / 'recipe.yaml'
    recipe.write_text(
        """literature:
  - parts:
      - {source: literature/test-2008/partial, range: [30, 1000]}
      - {source: literature/test-2008/total-ionization, range: [15, 25]}
    zero_at: 15.4
    pair: H2-electron
    kind: REACTION
    key: H2Ion1-electron-electron
"""
    )
    loaded = load_recipe(recipe)
    assert [str(part) for part, _ in loaded.literature[0].parts] == ['literature/test-2008/total-ionization', 'literature/test-2008/partial']  # sorted
    assert {str(r) for r in loaded.requirements} == {'literature/test-2008/total-ionization', 'literature/test-2008/partial'}
    output = tmp_path / 'combined.h5'
    assert main(['build', str(recipe), '-o', str(output), '--offline', '--allow-unreviewed']) == 0
    xsec = read_database(output).collision_pairs['H2-electron'].cross_sections[0]
    assert xsec.data[:, 0].tolist() == [15.4, 16.0, 20.0, 30.0, 50.0, 100.0, 1000.0]
    assert np.allclose(xsec.data[1:, 1], np.array([0.03, 0.28, 0.60, 0.80, 0.85, 0.20]) * 1e-20)
    assert 'total-ionization: 15-25 eV' in str(xsec.provenance.extra['* Parts']) and '15.4 eV' in str(xsec.provenance.extra['* Zero at'])
    assert 'literature-unreviewed' in [finding.rule for finding in run_checks(read_database(output))]

    for text, message in (
        ('  - parts:\n      - {source: literature/a/b, range: [1, 5]}\n      - {source: literature/a/c, range: [4, 9]}\n', 'overlap'),
        ('  - parts:\n      - {source: literature/a/b}\n', 'range'),
        ('  - parts:\n      - {source: lxcat/a/b, range: [1, 5]}\n', 'literature/'),
    ):
        recipe.write_text(f'literature:\n{text}    pair: H2-electron\n    kind: REACTION\n    key: x\n')
        with pytest.raises(RecipeError, match=message):
            load_recipe(recipe)
    recipe.write_text('literature:\n  - parts:\n      - {source: literature/test-2008/partial, range: [2000, 3000]}\n    pair: H2-electron\n    kind: REACTION\n    key: x\n')
    assert main(['build', str(recipe), '-o', str(tmp_path / 'empty.h5'), '--offline', '--allow-unreviewed']) == 1  # no data in the range
