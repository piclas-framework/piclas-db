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
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
import yaml  # noqa: E402

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.extract import vector  # noqa: E402
from piclas_db.extract.vector import ExtractError, extract, parse_label, values  # noqa: E402
from piclas_db.literature import find_extraction, read_extraction  # noqa: E402
from piclas_db.piclas_db import main  # noqa: E402
from piclas_db.store import Store  # noqa: E402
# ==================================================================================================================================
# Synthetic vector figures drawn with matplotlib (known data, no content of real papers)

X = np.array([0.035, 0.05, 0.056, 0.061, 0.071, 0.079, 0.087, 0.1, 0.12, 0.15])
Y = np.array([0.0, 7.7, 15.0, 15.5, 14.5, 17.1, 16.7, 18.5, 19.1, 18.1])
LOG_X = np.array([1.0, 10.0, 100.0, 1000.0])
LOG_Y = np.array([1.0e-20, 3.0e-20, 2.0e-20, 5.0e-21])


@pytest.fixture
def figures(tmp_path: pathlib.Path) -> dict[str, pathlib.Path]:
    plt.rcParams['pdf.fonttype'] = 42  # text as text, as in most journal PDFs
    linear = tmp_path / 'linear.pdf'
    fig, axis = plt.subplots(figsize=(4, 3))
    axis.errorbar(X, Y, yerr=0.08 * Y, fmt='s', mfc='none', mec='k', ecolor='k', capsize=2)
    axis.plot(X, 0.6 * Y, 'o', color='k')
    axis.plot(np.linspace(0.04, 0.15, 30), 10 + 40 * (np.linspace(0.04, 0.15, 30) - 0.04), '-', color='r')
    fig.savefig(linear)
    logarithmic = tmp_path / 'log.pdf'
    fig, axis = plt.subplots(figsize=(4, 3))
    axis.loglog(LOG_X, LOG_Y, '^', color='b')
    fig.savefig(logarithmic)
    plt.close('all')
    return {'linear': linear, 'log': logarithmic}


def test_labels() -> None:
    assert parse_label('10', '−20') == pytest.approx(1.0e-20)
    assert parse_label('6×10', '−21') == pytest.approx(6.0e-21)
    assert parse_label('0.04', '') == pytest.approx(0.04)
    assert parse_label('−5', '') == pytest.approx(-5.0)
    assert parse_label('abc', '') is None
    assert parse_label('2', '3') is None  # superscript without base 10


def test_linear_figure(figures: dict[str, pathlib.Path]) -> None:
    figure = extract(str(figures['linear']), 1)
    assert figure.x.scale == figure.y.scale == 'linear'
    assert figure.x.source == 'text' and figure.x.residual < 1.0e-5
    by_name = {series.name: series for series in figure.series}
    assert set(by_name) == {'circle-filled-black', 'square-open-black', 'line-1-red'}
    squares = values(figure, by_name['square-open-black'])
    assert np.allclose(squares[:, 0], X, atol=1.0e-5) and np.allclose(squares[:, 1], Y, atol=1.0e-3)  # PDF coordinates rounded to 1e-3 pt
    assert np.allclose(squares[1:, 3] - squares[1:, 2], 2 * 0.08 * Y[1:], rtol=1.0e-3)  # error bars
    circles = values(figure, by_name['circle-filled-black'])
    assert np.allclose(circles[:, 1], 0.6 * Y, atol=1.0e-3)
    line = values(figure, by_name['line-1-red'])
    assert len(line) == 30 and np.allclose(line[:, 1], 10 + 40 * (line[:, 0] - 0.04), atol=1.0e-3)


def test_logarithmic_figure(figures: dict[str, pathlib.Path]) -> None:
    figure = extract(str(figures['log']), 1)
    assert (figure.x.scale, figure.y.scale) == ('log', 'log')  # labels 10^n and 2x10^-20 with superscripts
    data = values(figure, figure.series[0])
    assert figure.series[0].name.startswith('triangle-filled')  # matplotlib draws markers as reusable objects without own colour
    assert np.allclose(data[:, 0], LOG_X, rtol=1.0e-3) and np.allclose(data[:, 1], LOG_Y, rtol=1.0e-3)


def test_given_labels_and_errors(figures: dict[str, pathlib.Path], tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    page_ticks = vector.ticks
    figure = extract(str(figures['linear']), 1)
    major = len(figure.x.labels)
    given = ','.join(str(value) for _, value in figure.x.labels)
    assert major >= 2 and given
    with pytest.raises(ExtractError, match='labels given'):
        extract(str(figures['linear']), 1, x_labels=[1.0, 2.0])
    with pytest.raises(ExtractError, match='page 2'):
        extract(str(figures['linear']), 2)
    with pytest.raises(ExtractError, match='frame 3'):
        extract(str(figures['linear']), 1, frame_index=3)
    # no text labels and no OCR available: the labels must be given
    monkeypatch.setattr(vector, 'text_labels', lambda *_: [])
    monkeypatch.setattr(vector.shutil, 'which', lambda _: None)
    with pytest.raises(ExtractError, match='give them'):
        extract(str(figures['linear']), 1)
    assert vector.ticks is page_ticks
    empty = tmp_path / 'empty.pdf'
    fig = plt.figure(figsize=(2, 2))
    fig.savefig(empty)
    plt.close(fig)
    with pytest.raises(ExtractError, match='no plot frame'):
        extract(str(empty), 1)


def test_command(figures: dict[str, pathlib.Path], tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv('PICLAS_DB_STORE', str(tmp_path / 'store'))
    assert main(['import', str(figures['linear']), '--literature', 'test-2025', '--doi', '10.0000/test']) == 0
    assert main(['extract', 'test-2025', '--page', '1', '--list']) == 0
    assert 'frame 0' in capsys.readouterr().out
    output = tmp_path / 'work'
    arguments = ['extract', 'test-2025', '--page', '1', '--figure', '3', '--name', 'fig3', '--x-unit', 'a.u.', '--mass-amu', '16', '--target-mass-amu', '32', '--y-unit', 'A^2', '-o', str(output)]
    assert main(arguments) == 0
    assert (output / 'p1-f0-review.png').stat().st_size > 1000
    record_file = output / 'fig3-square-open-black.extraction.yaml'
    record = yaml.safe_load(record_file.read_text())
    assert record['method'] == 'vector' and record['source']['figure'] == '3'
    assert record['calibration']['x']['labels_from'] == 'text' and record['result']['points'] == 10 and record['result']['error_bars'] >= 9
    assert record['environment']['pdfplumber']
    assert main(['literature', 'add', str(record_file)]) == 0
    entry = find_extraction(Store(tmp_path / 'store'), 'test-2025/fig3-square-open-black')
    data = read_extraction(entry)
    au = 2.18769126364e6
    lab = 0.5 * 16 * 1.66053906892e-27 * (X * au) ** 2 / 1.602176634e-19  # velocity -> laboratory energy
    assert np.allclose(data[:, 0], lab * 32 / (16 + 32), rtol=1.0e-4)  # -> collision energy
    assert np.allclose(data[:, 1], Y * 1.0e-20, atol=1.0e-23)
    assert main(['extract', 'unknown', '--page', '1']) == 1
    assert main(['extract', 'test-2025', '--page', '5', '-o', str(output)]) == 1
