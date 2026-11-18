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
from piclas_db.explain import candidates, explain_database
from piclas_db.model import CollisionPair, CrossSection, Database, XSecKind
from piclas_db.piclas_db import main
from piclas_db.recipe import load_recipe
from piclas_db.schema import Schema
from piclas_db.store import Store
from piclas_db.writer import write_database
from tests.test_import import LXCAT
from tests.test_literature import PDF
# ==================================================================================================================================
# An "old" database without provenance, made of: an LXCat process (unchanged), an LXCat process extended to higher energies, a table
# of a paper, a fit formula tabulated over the laboratory energy, and a dataset of unknown origin

FORMULA = 'expression: 4.0 / E**0.5\nparameters: {}\nrange: [1.0, 100.0]\npoints: 20\n'


def old_database(path: pathlib.Path) -> None:
    lab = np.geomspace(1.0, 100.0, 12)
    database = Database(path=str(path), schema=Schema.SPECIES_DATABASE)
    electron = CollisionPair(name='Ar-electron')
    electron.cross_sections += [
        CrossSection(kind=XSecKind.ELASTIC, key='ELASTIC', data=np.array([[0.0, 1.0e-20], [10.0, 2.0e-20]], dtype=np.float32).astype(np.float64)),
        CrossSection(kind=XSecKind.REACTION, group='REACTION', key='ArIon1-electron-electron', data=np.array([[15.7, 0.0], [100.0, 3.0e-20], [1.0e4, 1.0e-21], [1.0e5, 2.0e-22]])),
    ]
    ions = CollisionPair(name='H2-H2Ion1')
    ions.cross_sections += [
        CrossSection(kind=XSecKind.REACTION, group='REACTION', key='H2Ion1-H2', data=np.column_stack([lab, 4.0 / np.sqrt(lab) * 1.0e-20])),  # over E_lab
        CrossSection(kind=XSecKind.REACTION, group='REACTION', key='H-H2-HIon1', data=np.array([[16.0, 0.03e-20], [20.0, 0.28e-20], [50.0, 0.91e-20], [100.0, 0.90e-20]])),
        CrossSection(kind=XSecKind.ELASTIC, key='ELASTIC', data=np.array([[1.0, 5.0e-19], [2.0, 4.0e-19], [3.0, 3.0e-19]])),
    ]
    database.collision_pairs = {'Ar-electron': electron, 'H2-H2Ion1': ions}
    write_database(database, path)


def test_explain(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    store = tmp_path / 'store'
    monkeypatch.setenv('PICLAS_DB_STORE', str(store))
    (tmp_path / 'lxcat.txt').write_text(LXCAT)
    (tmp_path / 'paper.pdf').write_bytes(PDF)
    assert main(['import', str(tmp_path / 'lxcat.txt'), '--literature', 'x', '--doi', '1']) == 1  # (a PDF is needed for --literature)
    assert main(['import', str(tmp_path / 'lxcat.txt')]) == 0
    assert main(['import', str(tmp_path / 'paper.pdf'), '--literature', 'test-2008', '--doi', '10.0000/test']) == 0
    work = tmp_path / 'work'
    assert main(['literature', 'template', 'test-2008', 'table', '--page', '1', '--table', '1', '-o', str(work)]) == 0
    (work / 'table.csv').write_text((work / 'table.csv').read_text() + '16,0.03\n20,0.28\n50,0.91\n100,0.90\n')
    assert main(['literature', 'add', str(work / 'table.extraction.yaml')]) == 0
    assert main(['literature', 'template', 'test-2008', 'cx', '--page', '2', '--equation', '7', '--formula', '-o', str(work)]) == 0
    (work / 'cx.formula.yaml').write_text(FORMULA)
    record = yaml.safe_load((work / 'cx.extraction.yaml').read_text())
    record['columns']['energy'] = {'unit': 'eV', 'frame': 'lab', 'mass_amu': 2.0, 'target_mass_amu': 2.0}
    record['quantity']['assignment'] = {'pair': 'H2-H2Ion1'}
    (work / 'cx.extraction.yaml').write_text(yaml.safe_dump(record))
    assert main(['literature', 'add', str(work / 'cx.extraction.yaml')]) == 0

    old = tmp_path / 'old.h5'
    old_database(old)
    pool = candidates(Store(store))
    assert {candidate.kind for candidate in pool} == {'lxcat', 'table', 'formula'}
    from piclas_db.readers import read_database  # noqa: PLC0415

    results = {result.path: result for result in explain_database(read_database(old), pool)}
    elastic = results['/Cross-Sections/Ar-electron/ELASTIC']
    assert elastic.status == 'complete' and 'Elastic' in elastic.parts[0].candidate.name  # float32 copy of the LXCat data
    ionization = results['/Cross-Sections/Ar-electron/REACTION/ArIon1-electron-electron']
    assert ionization.status == 'partial' and ionization.unexplained == [(1.0e4, 1.0e-21), (1.0e5, 2.0e-22)]  # extended beyond the source
    cx = results['/Cross-Sections/H2-H2Ion1/REACTION/H2Ion1-H2']
    assert cx.status == 'complete' and cx.parts[0].candidate.note == 'over the laboratory energy'
    assert results['/Cross-Sections/H2-H2Ion1/REACTION/H-H2-HIon1'].status == 'complete'
    assert results['/Cross-Sections/H2-H2Ion1/ELASTIC'].status == 'unknown'
    assert ionization.zero_at == pytest.approx(15.7)  # sigma = 0 at the threshold is reported separately

    capsys.readouterr()
    report, draft = tmp_path / 'report.md', tmp_path / 'draft.yaml'
    assert main(['rebuild', str(old), '--explain', '--report', str(report), '--recipe-out', str(draft)]) == 0
    out = capsys.readouterr().out
    assert '5 cross-sections: 3 complete, 0 combined, 1 partial, 1 without source in the store; 1 over the laboratory energy' in out
    assert '** over the laboratory energy **' in out
    assert '| `/Cross-Sections/H2-H2Ion1/REACTION/H2Ion1-H2` | complete |' in report.read_text()
    recipe = load_recipe(draft)  # the draft is a valid recipe
    assert recipe.cross_sections[0].database == 'Test-A' and recipe.cross_sections[0].processes == ['E + Ar -> E + Ar']
    assert {entry.key for entry in recipe.literature} == {'H2Ion1-H2', 'H-H2-HIon1'}
    assert 'only over the laboratory energy' in draft.read_text() and 'H2-H2Ion1/ELASTIC: unknown' in draft.read_text()
    assert main(['rebuild', str(old)]) == 1  # without --explain: -o needed
    assert main(['rebuild', str(tmp_path / 'missing.h5'), '--explain']) == 1
