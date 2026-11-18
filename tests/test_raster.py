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
import io
import pathlib
import shutil
from typing import Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
import yaml  # noqa: E402
from PIL import Image  # noqa: E402

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.extract.raster import extract_raster, is_scanned, link, raster_figure_frames, shape_of  # noqa: E402
from piclas_db.extract.vector import ExtractError, values  # noqa: E402
from piclas_db.piclas_db import main  # noqa: E402
# ==================================================================================================================================
# Synthetic scan: a figure drawn with matplotlib, rendered at 150 dpi, reduced to black and white and stored as image in a PDF
# (300 dpi), like the scanned journals; three series of filled symbols with invented values

X = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0])
SERIES = {'s': 3.0 + 0.1 * X, 'o': 2.0 + 0.05 * X, '^': 1.0 + 0.08 * X}
X_TICKS = [0, 2, 4, 6, 8]
Y_TICKS = [0, 1, 2, 3, 4]


@pytest.fixture
def scan(tmp_path: pathlib.Path) -> pathlib.Path:
    figure, axis = plt.subplots(figsize=(4, 3.5))
    for marker, y in SERIES.items():
        axis.plot(X, y, marker, color='k', markersize=6, linestyle='none')
    axis.set_xlim(0, 8)
    axis.set_ylim(0, 4)
    axis.set_xticks(X_TICKS)
    axis.set_yticks(Y_TICKS)
    axis.tick_params(labelsize=14)
    buffer = io.BytesIO()
    figure.savefig(buffer, format='png', dpi=150)
    plt.close(figure)
    image = Image.open(buffer).convert('L').point(lambda value: 0 if value < 160 else 255).convert('1')
    page = Image.new('1', (2550, 3300), 1)  # letter page at 300 dpi
    page.paste(image.resize((image.width * 2, image.height * 2)), (300, 300))
    path = tmp_path / 'scan.pdf'
    page.save(path, resolution=300)
    return path


def test_shapes_and_linking() -> None:
    square = np.ones((10, 10), dtype=bool)
    triangle = np.array([[abs(column - 5) <= row // 2 for column in range(11)] for row in range(11)])
    assert shape_of(square) == 'square'
    assert shape_of(triangle) == 'triangle'
    assert shape_of(triangle[::-1]) == 'triangle-down'
    points: list[tuple[float, float, Optional[str], bool]] = [(10.0 * i, 100.0 + i, 'square', False) for i in range(5)]
    points += [(10.0 * i + 5, 300.0 - 2 * i, 'circle', False) for i in range(5)]
    tracks = link(points, tolerance=20.0, max_step=50.0)
    assert sorted(len(track) for track in tracks) == [5, 5]


def test_scanned_figure(scan: pathlib.Path) -> None:
    assert is_scanned(str(scan), 1)
    frames = raster_figure_frames(str(scan), 1)
    assert len(frames) == 1
    figure = extract_raster(str(scan), 1, x_labels=[float(v) for v in X_TICKS], y_labels=[float(v) for v in Y_TICKS])
    assert (figure.x.source, figure.y.source) == ('given', 'given')
    assert len(figure.series) == 3
    found = {series.name.split('-')[0]: values(figure, series) for series in figure.series}
    assert set(found) == {'square', 'circle', 'triangle'}
    for marker, name in (('s', 'square'), ('o', 'circle'), ('^', 'triangle')):
        data = found[name]
        assert np.allclose(data[:, 0], X, atol=0.05)  # about one pixel of the 150 dpi rendering
        assert np.allclose(data[:, 1], SERIES[marker], atol=0.03)
    with pytest.raises(ExtractError, match='labels given'):
        extract_raster(str(scan), 1, x_labels=[1.0])
    with pytest.raises(ExtractError, match='frame 2'):
        extract_raster(str(scan), 1, frame_index=2)


@pytest.mark.skipif(shutil.which('tesseract') is None, reason='Tesseract not installed')
def test_scanned_figure_ocr(scan: pathlib.Path) -> None:
    figure = extract_raster(str(scan), 1)
    assert figure.x.source == 'ocr' and figure.x.residual < 0.05
    assert {round(value) for _, value in figure.y.labels} <= set(Y_TICKS)


def test_command(scan: pathlib.Path, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv('PICLAS_DB_STORE', str(tmp_path / 'store'))
    assert main(['import', str(scan), '--literature', 'scan-1989', '--doi', '10.0000/scan']) == 0
    assert main(['extract', 'scan-1989', '--page', '1', '--list']) == 0
    assert 'frame 0' in capsys.readouterr().out
    output = tmp_path / 'work'
    arguments = ['extract', 'scan-1989', '--page', '1', '--x-labels', '0,2,4,6,8', '--y-labels', '0,1,2,3,4', '--x-unit', 'keV', '--y-unit', '1e-16 cm^2', '-o', str(output)]
    assert main(arguments) == 0
    records = sorted(output.glob('*.extraction.yaml'))
    assert len(records) == 3
    record = yaml.safe_load(records[0].read_text())
    assert record['method'] == 'raster' and record['parameters']['resolution_dpi'] == 300
    assert 'one pixel' in record['accuracy']['extraction'] and record['environment']['scikit-image']
    assert (output / 'p1-f0-review.png').is_file()
    assert main(['literature', 'add', str(records[0])]) == 0


def crossing_scan(path: pathlib.Path) -> None:
    """Two curves of filled symbols that cross, and one curve of open circles"""
    figure, axis = plt.subplots(figsize=(4, 3.5))
    axis.plot(X, 0.5 + 0.45 * X, 's', color='k', markersize=7)  # rising
    axis.plot(X, 3.4 - 0.45 * X, 's', color='k', markersize=7)  # falling, crosses the rising curve near x = 3.2
    axis.plot(X, np.full_like(X, 3.85), 'o', mfc='none', mec='k', markersize=8, mew=1.2)  # open circles, apart from the squares
    axis.set_xlim(0, 8)
    axis.set_ylim(0, 4)
    axis.set_xticks(X_TICKS)
    axis.set_yticks(Y_TICKS)
    buffer = io.BytesIO()
    figure.savefig(buffer, format='png', dpi=150)
    plt.close(figure)
    image = Image.open(buffer).convert('L').point(lambda value: 0 if value < 160 else 255).convert('1')
    page = Image.new('1', (2550, 3300), 1)
    page.paste(image.resize((image.width * 2, image.height * 2)), (300, 300))
    page.save(path, resolution=300)


def test_open_symbols_seeds_and_points(tmp_path: pathlib.Path) -> None:
    path = tmp_path / 'crossing.pdf'
    crossing_scan(path)
    x_labels, y_labels = [float(v) for v in X_TICKS], [float(v) for v in Y_TICKS]
    automatic = extract_raster(str(path), 1, x_labels=x_labels, y_labels=y_labels)
    open_series = [series for series in automatic.series if '-open' in series.name]
    assert len(open_series) == 1 and len(open_series[0].points) == 7  # open circles found and kept apart from the filled ones
    assert np.allclose(values(automatic, open_series[0])[:, 1], 3.85, atol=0.03)

    # crossing curves: one seed per curve (two points give the direction)
    seeded = extract_raster(str(path), 1, x_labels=x_labels, y_labels=y_labels, seeds=[(1.0, 0.95, 2.0, 1.4), (1.0, 2.95)])
    rising, falling = (values(seeded, series) for series in seeded.series)
    assert np.allclose(rising[:, 1], 0.5 + 0.45 * rising[:, 0], atol=0.03) and len(rising) == 7
    assert np.allclose(falling[:, 1], 3.4 - 0.45 * falling[:, 0], atol=0.03) and len(falling) == 7
    with pytest.raises(ExtractError, match='no symbol near'):
        extract_raster(str(path), 1, x_labels=x_labels, y_labels=y_labels, seeds=[(4.0, 3.05)])  # between the curves

    # frame and calibration given in pt (as read from the grid image), for scans whose axes are not found
    frame = automatic.frame
    points_x = [(position, value) for position, value in automatic.x.labels]
    points_y = [(position, value) for position, value in automatic.y.labels]
    given = extract_raster(str(path), 1, frame_box=frame, x_points=points_x, y_points=points_y)
    assert given.x.source == 'points' and len(given.series) == len(automatic.series)


def test_grid_and_command_options(scan: pathlib.Path, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('PICLAS_DB_STORE', str(tmp_path / 'store'))
    assert main(['import', str(scan), '--literature', 'scan-1990', '--doi', '10.0000/grid']) == 0
    output = tmp_path / 'work'
    assert main(['extract', 'scan-1990', '--page', '1', '--list', '-o', str(output)]) == 0
    assert (output / 'p1-grid.png').stat().st_size > 1000
    figure = extract_raster(str(scan), 1, x_labels=[float(v) for v in X_TICKS], y_labels=[float(v) for v in Y_TICKS])
    box = ','.join(f'{value:.2f}' for value in figure.frame)
    x_points = ','.join(f'{position:.3f}={value:g}' for position, value in figure.x.labels)
    y_points = ','.join(f'{position:.3f}={value:g}' for position, value in figure.y.labels)
    arguments = ['extract', 'scan-1990', '--page', '1', '--frame-box', box, '--x-points', x_points, '--y-points', y_points, '--seeds', '1,3.1', '-o', str(output)]
    assert main(arguments) == 0
    record = yaml.safe_load(next(output.glob('*.extraction.yaml')).read_text())
    assert record['parameters']['seeds'] == '1,3.1' and record['calibration']['x']['labels_from'] == 'points'
    assert main([*arguments[:-2], '--seeds', '1,2,3', '-o', str(output)]) == 1  # three numbers: not a seed
