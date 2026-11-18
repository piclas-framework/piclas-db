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
import yaml

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.formula import FormulaError, compile_formula, tabulate
from piclas_db.literature import find_extraction, read_extraction
from piclas_db.piclas_db import main
from piclas_db.readers import read_database
from piclas_db.store import Store
from tests.test_literature import PDF
# ==================================================================================================================================
# Invented formula in the style of fit formulas of review papers

FORMULA = """expression: a / E**b * exp(-c / (E - 2.0)**1.5)
parameters: {a: 4.0, b: 0.65, c: 3.0}
threshold: 2.0
range: [1.0, 1000.0]
points: 50
"""


def test_compile_and_tabulate() -> None:
    function = compile_formula('a * E**2 + sqrt(E) - log10(E) + abs(-1) + exp(0) * log(1)', {'a': 2.0})
    assert function(np.array([1.0, 4.0])).tolist() == pytest.approx([4.0, 35.0 - np.log10(4.0)])
    assert function(np.array([2.0]))[0] == pytest.approx(2 * 4 + np.sqrt(2) - np.log10(2) + 1)
    assert compile_formula('E^2', {})(np.array([3.0]))[0] == pytest.approx(9.0)  # ^ as power
    assert compile_formula('-E + +1', {})(np.array([3.0]))[0] == pytest.approx(-2.0)
    assert compile_formula('5', {})(np.array([1.0, 2.0])).tolist() == [5.0, 5.0]  # constants give a full grid
    for forbidden in ('__import__("os")', 'E.real', 'open(1)', 'lambda: 1', '[E]', 'exp(E, 2)', 'E if E else 1', 'E +'):
        with pytest.raises(FormulaError):
            compile_formula(forbidden, {})
    energy, sigma = tabulate(yaml.safe_load(FORMULA))
    assert energy[0] == pytest.approx(2.0) and not sigma[0] > 0.0  # threshold point, zero
    assert np.all(np.diff(energy) > 0.0) and np.all(sigma >= 0.0) and np.all(sigma[-10:] > 0.0)
    for broken, message in (
        ({'expression': 'E'}, 'range'),
        ({'expression': 'E', 'range': [5, 1]}, '0 < min'),
        ({'expression': '1/(E-2)', 'range': [1, 4], 'points': 3}, 'finite'),
        ({'expression': '-E', 'range': [1, 3]}, 'negative'),
    ):
        with pytest.raises(FormulaError, match=message):
            tabulate(broken)


def test_formula_extraction_and_frames(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv('PICLAS_DB_STORE', str(tmp_path / 'store'))
    (tmp_path / 'report.pdf').write_bytes(PDF)
    assert main(['import', str(tmp_path / 'report.pdf'), '--literature', 'review-2003', '--reference', 'A. Author, Report 1 (2003)']) == 0
    work = tmp_path / 'work'
    assert main(['literature', 'template', 'review-2003', 'cid', '--page', '85', '--equation', '209', '--formula', '-o', str(work)]) == 0
    assert (work / 'cid.formula.yaml').read_text().startswith('# Fit formula')
    (work / 'cid.formula.yaml').write_text(FORMULA)
    record_file = work / 'cid.extraction.yaml'
    record = yaml.safe_load(record_file.read_text())
    assert record['source']['equation'] == '209' and record['formula'] is True

    # laboratory energy without masses is refused: PICLas uses the collision energy
    record['columns']['energy'] = {'unit': 'eV', 'frame': 'lab'}
    record_file.write_text(yaml.safe_dump(record))
    assert main(['literature', 'add', str(record_file)]) == 1
    assert 'target_mass_amu' in capsys.readouterr().out
    record['columns']['energy'].update({'mass_amu': 2.0, 'target_mass_amu': 2.0})
    record_file.write_text(yaml.safe_dump(record))
    assert main(['literature', 'add', str(record_file)]) == 0
    data = read_extraction(find_extraction(Store(tmp_path / 'store'), 'review-2003/cid'))
    energy, sigma = tabulate(yaml.safe_load(FORMULA))
    assert np.allclose(data[:, 0], energy / 2.0)  # equal masses: E_cm = E_lab / 2
    assert np.allclose(data[:, 1], sigma * 1.0e-20)

    recipe = tmp_path / 'recipe.yaml'
    recipe.write_text('literature:\n  - source: literature/review-2003/cid\n    pair: H2-H2Ion1\n    kind: REACTION\n    key: H-H2-HIon1\n')
    output = tmp_path / 'database.h5'
    assert main(['build', str(recipe), '-o', str(output), '--offline', '--allow-unreviewed']) == 0
    xsec = read_database(output).collision_pairs['H2-H2Ion1'].cross_sections[0]
    assert 'equation 209' in str(xsec.provenance.reference) and len(xsec.data) == len(energy)  # grid above the threshold

    assert main(['literature', 'template', 'review-2003', 'cid', '--formula', '-o', str(work)]) == 1  # exists
    (work / 'other.formula.yaml').write_text('expression: E.real\nrange: [1, 2]\n')
    other = dict(record, name='other', data='other.formula.yaml')
    (work / 'other.extraction.yaml').write_text(yaml.safe_dump(other))
    assert main(['literature', 'add', str(work / 'other.extraction.yaml')]) == 1
    assert 'formula' in capsys.readouterr().out
