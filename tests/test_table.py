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
import shutil

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
import yaml  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.extract.table import ExtractError, extract_table, header_unit, parse_number  # noqa: E402
from piclas_db.literature import find_extraction, read_extraction  # noqa: E402
from piclas_db.piclas_db import main  # noqa: E402
from piclas_db.store import Store  # noqa: E402
# ==================================================================================================================================
# Synthetic pages in the style of journal papers (invented values): a two-column page with a table that continues on the next page,
# and a single-column page with a parameter table whose caption is below it

ROWS_1 = [('0.5', '1.25'), ('1', '2.5'), ('2', '0.056 5'), ('5', '9.70E−07')]
ROWS_2 = [('10', '3.75'), ('20', '4.5')]
PARAMETERS = [('a1', '10.082', '33.777'), ('a2', '9.5185(-4)∗', '62.880'), ('a3', '−2.7993', '−11.310')]


def text(figure: plt.Figure, x: float, y: float, content: str) -> None:
    figure.text(x / 612, 1 - y / 792, content, fontsize=9, family='DejaVu Sans')


def table_page(figure: plt.Figure, caption: str, rows: list[tuple[str, str]], header: bool) -> None:
    text(figure, 60, 60, caption)
    y = 80.0
    if header:
        text(figure, 70, y, 'Energy')
        text(figure, 150, y, 'Cross section')
        text(figure, 70, y + 11, '(eV)')
        text(figure, 150, y + 11, '(10−16 cm2)')
        y += 30
    for energy, value in rows:
        text(figure, 75, y, energy)
        text(figure, 160, y, value)
        y += 12
    for line in range(12):  # right column: running text, never crossing the middle of the page
        text(figure, 330, 60 + 12 * line, 'running text in the right column')
    text(figure, 60, 400, 'Running text below the table in the left column.')


@pytest.fixture
def paper(tmp_path: pathlib.Path) -> pathlib.Path:
    plt.rcParams['pdf.fonttype'] = 42
    path = tmp_path / 'paper.pdf'
    with PdfPages(path) as pdf:
        figure = plt.figure(figsize=(8.5, 11))
        table_page(figure, 'TABLE 3. Recommended values of the test cross section', ROWS_1, header=True)
        pdf.savefig(figure)
        figure = plt.figure(figsize=(8.5, 11))
        table_page(figure, 'TABLE 3. Recommended values of the test cross section—Continued', ROWS_2, header=True)
        pdf.savefig(figure)
        figure = plt.figure(figsize=(8.5, 11))
        text(figure, 60, 100, 'Transition')
        text(figure, 160, 100, '1s → 2s')
        text(figure, 260, 100, '1s → 2p')
        for index, (label, first, second) in enumerate(PARAMETERS):
            text(figure, 60, 120 + 12 * index, label)
            text(figure, 160, 120 + 12 * index, first)
            text(figure, 260, 120 + 12 * index, second)
        text(figure, 60, 170, 'Table 2: Values of parameters a i in Eq. (5) for the test transitions.')
        text(figure, 60, 230, 'A long line of running text that crosses the middle of this single column page from left to right.')
        pdf.savefig(figure)
    plt.close('all')
    return path


def test_numbers_and_units() -> None:
    assert parse_number('9.70E−07') == pytest.approx(9.7e-7)
    assert parse_number('9.5185(-4)∗') == pytest.approx(9.5185e-4)
    assert parse_number('−2.7993') == pytest.approx(-2.7993)
    assert parse_number('-') is None and parse_number('a 1') is None
    assert header_unit('Cross section (cid:1)10−17 cm2(cid:2)') == '1e-17 cm^2'
    assert header_unit('Energy (cid:1)eV(cid:2)') == 'eV'
    assert header_unit('(keV)') == 'keV'
    assert header_unit('σ (Å2)') == 'A^2'
    assert header_unit('Transition') is None


def test_two_column_table_with_continuation(paper: pathlib.Path) -> None:
    table = extract_table(str(paper), [1, 2], '3')
    assert table.pages == [1, 2] and table.source == 'text'
    assert [row[0] for row in table.rows] == ['0.5', '1', '2', '5', '10', '20']
    assert table.rows[2][1] == '0.0565'  # digit groups joined
    assert header_unit(table.header[0]) == 'eV' and header_unit(table.header[1]) == '1e-16 cm^2'
    assert all('running' not in cell for row in table.rows for cell in row)  # other column and text below excluded


def test_parameter_table_caption_below(paper: pathlib.Path) -> None:
    table = extract_table(str(paper), [3], '2')
    assert [row[0] for row in table.rows] == ['a1', 'a2', 'a3']
    assert parse_number(table.rows[1][1]) == pytest.approx(9.5185e-4)
    assert table.header[0] == 'Transition' and '2s' in table.header[1]
    with pytest.raises(ExtractError, match='not found'):
        extract_table(str(paper), [3], '7')
    with pytest.raises(ExtractError, match='does not exist'):
        extract_table(str(paper), [9], '2')


@pytest.mark.skipif(shutil.which('tesseract') is None, reason='Tesseract not installed')
def test_scanned_table(paper: pathlib.Path, tmp_path: pathlib.Path) -> None:
    import pdfplumber  # noqa: PLC0415

    with pdfplumber.open(paper) as pdf:
        image = pdf.pages[0].to_image(resolution=300).original.convert('RGB')
    scan = tmp_path / 'scan.pdf'
    image.save(scan, resolution=300)
    table = extract_table(str(scan), [1], '3')
    assert table.source == 'ocr'
    values = [parse_number(row[1]) for row in table.rows]
    assert values[:2] == [pytest.approx(1.25), pytest.approx(2.5)]


def test_command(paper: pathlib.Path, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv('PICLAS_DB_STORE', str(tmp_path / 'store'))
    assert main(['import', str(paper), '--literature', 'test-2008', '--doi', '10.0000/test']) == 0
    output = tmp_path / 'work'
    assert main(['extract', 'test-2008', '--page', '1-2', '--table', '3', '--by', 'tester', '-o', str(output)]) == 0
    assert (output / 'table3-table.csv').read_text().startswith('Energy')
    record = yaml.safe_load((output / 'table3-c1.extraction.yaml').read_text())
    assert record['method'] == 'text' and record['source']['table'] == '3' and record['source']['page'] == '1, 2'
    assert record['columns']['cross_section']['unit'] == '1e-16 cm^2'
    assert main(['literature', 'add', str(output / 'table3-c1.extraction.yaml')]) == 0
    data = read_extraction(find_extraction(Store(tmp_path / 'store'), 'test-2008/table3-c1'))
    assert np.allclose(data[:, 1], np.array([1.25, 2.5, 0.0565, 9.7e-7, 3.75, 4.5]) * 1e-20)
    capsys.readouterr()
    assert main(['extract', 'test-2008', '--page', '3', '--table', '2', '-o', str(output)]) == 0
    assert 'parameter table' in capsys.readouterr().out
    assert main(['extract', 'test-2008', '--page', '3', '--table', '9', '-o', str(output)]) == 1


def test_redo_table(paper: pathlib.Path, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv('PICLAS_DB_STORE', str(tmp_path / 'store'))
    assert main(['import', str(paper), '--literature', 'test-2008', '--doi', '10.0000/test']) == 0
    output = tmp_path / 'work'
    assert main(['extract', 'test-2008', '--page', '1-2', '--table', '3', '-o', str(output)]) == 0
    assert main(['literature', 'add', str(output / 'table3-c1.extraction.yaml')]) == 0
    capsys.readouterr()
    assert main(['extract', '--redo', 'test-2008/table3-c1', '-o', str(tmp_path / 'redo')]) == 0
    assert '6 points, identical' in capsys.readouterr().out


def test_formula_with_parameters_from_table(paper: pathlib.Path, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv('PICLAS_DB_STORE', str(tmp_path / 'store'))
    assert main(['import', str(paper), '--literature', 'test-2003', '--reference', 'A. Author, Report (2003)']) == 0
    work = tmp_path / 'work'
    assert main(['extract', 'test-2003', '--page', '3', '--table', '2', '-o', str(work)]) == 0
    record = yaml.safe_load((work / 'table2.extraction.yaml').read_text())
    assert record['parameter_table'] is True and record['data'] == 'table2-table.csv'
    assert main(['literature', 'add', str(work / 'table2.extraction.yaml')]) == 0

    # one formula per column: parameters a1, a2 from the column '1s -> 2p' (the second value column)
    assert main(['literature', 'template', 'test-2003', 'fit', '--page', '3', '--equation', '5', '--formula', '--parameters-from', 'test-2003/table2', '--column', '2', '-o', str(work)]) == 0
    formula = yaml.safe_load((work / 'fit.formula.yaml').read_text())
    assert formula['parameters_from'] == {'table': 'test-2003/table2', 'column': 2, 'rows': {}}
    formula.update({'expression': 'a1 + a2 * E + c', 'parameters': {'c': 1.0}, 'range': [1.0, 10.0], 'points': 5})
    (work / 'fit.formula.yaml').write_text(yaml.safe_dump(formula))
    assert main(['literature', 'add', str(work / 'fit.extraction.yaml')]) == 0
    stored = find_extraction(Store(tmp_path / 'store'), 'test-2003/fit')
    resolved = stored.meta['extraction']['formula']
    assert resolved['parameters'] == {'c': 1.0, 'a1': pytest.approx(33.777), 'a2': pytest.approx(62.880)}
    assert resolved['parameters_from']['sha256'] == find_extraction(Store(tmp_path / 'store'), 'test-2003/table2').meta['sha256']
    data = read_extraction(stored)
    assert np.allclose(data[:, 1], (33.777 + 62.880 * data[:, 0] + 1.0) * 1.0e-20)

    # errors: unknown row, unknown column, a table that is not a parameter table
    for change, message in (
        ({'expression': 'a9 * E'}, 'parameter a9'),
        ({'parameters_from': {'table': 'test-2003/table2', 'column': 'nope'}}, 'column'),
        ({'parameters_from': {'table': 'test-2003/table2', 'column': 7}}, 'column 7'),
    ):
        (work / 'fit.formula.yaml').write_text(yaml.safe_dump({**formula, **change}))
        assert main(['literature', 'add', str(work / 'fit.extraction.yaml')]) == 1
        assert message in capsys.readouterr().out
    assert main(['extract', 'test-2003', '--page', '1-2', '--table', '3', '-o', str(work)]) == 0
    assert main(['literature', 'add', str(work / 'table3-c1.extraction.yaml')]) == 0
    (work / 'fit.formula.yaml').write_text(yaml.safe_dump({**formula, 'parameters_from': {'table': 'test-2003/table3-c1', 'column': 1}}))
    assert main(['literature', 'add', str(work / 'fit.extraction.yaml')]) == 1
    assert 'not a parameter table' in capsys.readouterr().out
