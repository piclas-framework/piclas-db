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
from piclas_db.piclas_db import main
from piclas_db.plot import BOLTZMANN, ELECTRON_MASS, EV, PlotError, Source, plot_cross_sections, plot_levels, rate_coefficient, reduced_mass
from piclas_db.readers import DatabaseReadError
from piclas_db.sources.any import read_any
from tests.test_import import LXCAT, NIST_CSV
# ==================================================================================================================================


@pytest.fixture
def files(tmp_path: pathlib.Path) -> dict[str, pathlib.Path]:
    lxcat = tmp_path / 'argon.txt'
    lxcat.write_text(LXCAT)
    nist = tmp_path / 'Ar_I_levels.csv'
    nist.write_text(NIST_CSV)
    old = tmp_path / 'old.h5'
    with h5py.File(old, 'w') as h5:
        h5['Ar-electron/ELASTIC'] = np.array([[0.0, 1.0e-20], [10.0, 2.1e-20]])
        h5['Ar-electron/REACTION/electron-electron-ArIon1'] = np.array([[15.7, 0.0], [100.0, 3.0e-20]])
    levels = tmp_path / 'levels.h5'
    with h5py.File(levels, 'w') as h5:
        h5['Ar'] = np.array([[1.0, 0.0], [5.0, 93000.0 / 1.438776877]])  # in cm^-1 by mistake
    return {'lxcat': lxcat, 'nist': nist, 'old': old, 'levels': levels}


def test_rate_coefficient() -> None:
    # Constant cross-section: k = sigma * mean speed = sigma * sqrt(8 k_B T / (pi m))
    temperatures = np.array([1.0e3, 1.0e4, 1.0e5])
    data = np.array([[0.0, 1.0e-19], [1.0e4, 1.0e-19]])
    expected = 1.0e-19 * np.sqrt(8.0 * BOLTZMANN * temperatures / (np.pi * ELECTRON_MASS))
    assert rate_coefficient(data, temperatures, ELECTRON_MASS) == pytest.approx(expected, rel=1.0e-3)
    # Step at a threshold E0: k = sigma * mean speed * (1 + E0/kT) exp(-E0/kT)
    threshold = 10.0
    step = np.array([[threshold, 1.0e-20], [1.0e4, 1.0e-20]])
    kt = BOLTZMANN * temperatures[1:] / EV
    expected = 1.0e-20 * np.sqrt(8.0 * BOLTZMANN * temperatures[1:] / (np.pi * ELECTRON_MASS)) * (1.0 + threshold / kt) * np.exp(-threshold / kt)
    assert rate_coefficient(step, temperatures[1:], ELECTRON_MASS) == pytest.approx(expected, rel=2.0e-3)


def test_read_any(files: dict[str, pathlib.Path], tmp_path: pathlib.Path) -> None:
    lxcat = read_any(files['lxcat'])
    assert set(lxcat.collision_pairs) == {'Ar-electron', 'Ar-ArIon1'}
    assert lxcat.collision_pairs['Ar-electron'].of_kind(XSecKind.REACTION)[0].key == 'ArIon1-electron-electron'
    levels = read_any(files['nist']).species['Ar'].electronic_levels
    assert levels is not None
    assert len(levels) == 2
    assert read_any(files['old']).collision_pairs
    (tmp_path / 'notes.txt').write_text('nothing')
    for path in (tmp_path / 'notes.txt', tmp_path / 'missing.txt'):
        with pytest.raises(DatabaseReadError):
            read_any(path)
    (tmp_path / 'levels.csv').write_text(NIST_CSV)
    with pytest.raises(DatabaseReadError):
        read_any(tmp_path / 'levels.csv')  # species unknown
    assert 'Ar' in read_any(tmp_path / 'levels.csv', species='Ar').species


def test_figures(files: dict[str, pathlib.Path]) -> None:
    sources = [Source('LXCat', read_any(files['lxcat'])), Source('old', read_any(files['old']))]
    figure = plot_cross_sections(sources, 'electron-Ar', compare=True)  # pair order does not matter
    assert len(figure.axes) == 2
    assert len(figure.axes[0].get_lines()) == 4  # elastic and ionization from both sources
    figure = plot_cross_sections(sources, 'Ar-electron', kinds=['REACTION'], rate=True)
    assert len(figure.axes[0].get_lines()) == 2
    with pytest.raises(PlotError):
        plot_cross_sections(sources, 'Xe-electron')
    with pytest.raises(PlotError):
        plot_cross_sections(sources, 'Ar-ArIon1', rate=True)  # masses unknown
    assert reduced_mass('Ar-electron', sources) == ELECTRON_MASS
    levels = plot_levels([Source('NIST', read_any(files['nist'])), Source('old', read_any(files['levels']))], 'Ar')
    assert len(levels.axes[0].get_lines()) == 2
    with pytest.raises(PlotError):
        plot_levels(sources, 'Xe')


def test_plot_command(files: dict[str, pathlib.Path], tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / 'plot.png'
    assert main(['plot', str(files['lxcat']), str(files['old']), '--pair', 'Ar-electron', '--compare', '-o', str(output)]) == 0
    assert output.stat().st_size > 1000
    assert main(['plot', str(files['lxcat']), '--pair', 'Ar-electron', '--rate', '--temperatures', '1e3:1e5:20', '-o', str(tmp_path / 'r.pdf')]) == 0
    assert main(['plot', str(files['nist']), str(files['levels']), '--species', 'Ar', '--label', 'NIST', 'old', '-o', str(tmp_path / 'l.svg')]) == 0
    assert main(['plot', str(files['lxcat']), '--list']) == 0
    assert '--pair Ar-ArIon1' in capsys.readouterr().out
    assert main(['plot', str(files['lxcat'])]) == 1  # nothing selected: lists the contents
    assert main(['plot', str(files['lxcat']), '--pair', 'Ar-electron', '--label', 'a', 'b']) == 1
    assert main(['plot', str(files['lxcat']), '--pair', 'Ar-electron', '--rate', '--temperatures', '5:1']) == 1
    assert main(['plot', str(files['lxcat']), '--pair', 'Xe-electron']) == 1
    assert main(['plot', str(tmp_path / 'missing.h5'), '--pair', 'Ar-electron']) == 1
