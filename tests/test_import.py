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
import yaml

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.piclas_db import main
from piclas_db.sources.identify import IdentifyError, database_slug, identify
from piclas_db.sources.lxcat import parse_lxcat, validate
from piclas_db.sources.nist import parse_nist_levels, piclas_species
from piclas_db.store import Store, default_store
# ==================================================================================================================================
# Synthetic files in the formats of the providers (structure only, invented numbers; no third-party data)

LXCAT = """LXCat, www.lxcat.net
Generated on 01 Jun 2026. All rights reserved.

RECOMMENDED REFERENCE FORMAT
- Test-A database, www.lxcat.net, retrieved on June 1, 2026.
- Test-B database, www.lxcat.net, retrieved on June 1, 2026.

xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
DATABASE:         Test-A (version 1)
PERMLINK:         www.lxcat.net/Test-A
xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

ELASTIC
Ar
 1.0e-5
SPECIES: e / Ar
PROCESS: E + Ar -> E + Ar, Elastic
PARAM.:  m/M = 0.00001, complete set
COMMENT: invented numbers
UPDATED: 2020-01-01 00:00:00
COLUMNS: Energy (eV) | Cross section (m2)
-----------------------------
 0.0e+0\t1.0e-20
 1.0e+1\t2.0e-20
-----------------------------

IONIZATION
Ar
 15.7
SPECIES: e / Ar
PROCESS: E + Ar -> E + E + Ar+, Ionization
PARAM.:  E = 15.7 eV, complete set
COLUMNS: Energy (eV) | Cross section (m2)
-----------------------------
 1.57e+1\t0.0
 1.00e+2\t3.0e-20
-----------------------------
xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
DATABASE:         Test-B database
PERMLINK:         www.lxcat.net/Test-B
xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

SPECIES: Ar^+ / Ar
PROCESS: Ar+ + Ar -> , Backscat
PARAM.:  Mi = 39.948, Mi/M = 1, complete set
COMMENT: first comment
COMMENT: second comment
UPDATED: 2011-10-30 07:03:24
COLUMNS: Energy (eV) | Cross section (m2)
-----------------------------
 0.0e+0\t1.0e-18
 1.0e+0\t5.0e-19
-----------------------------
"""

NIST_CSV = '"Configuration","Term","J","Level (cm-1)","Uncertainty (cm-1)"\n"a","1S","0","0.0000",""\n"b","2[3/2]","2","93000.0","0.0006"\n"Ar II (x)","Limit","","[127109.842]",""\n'
NIST_TEXT = 'Ar II\n---------------------------\n Configuration | Term | J   | Level (eV) |\n---------------------------\n 3s2.3p5 | 2P* | 3/2 | 0.0000000 |\n         |     | 1/2 | 0.1700000 |\n'


@pytest.fixture
def downloads(tmp_path: pathlib.Path) -> pathlib.Path:
    directory = tmp_path / 'Downloads'
    directory.mkdir()
    (directory / 'lxcat.txt').write_text(LXCAT)
    (directory / 'Ar_I_levels.csv').write_text(NIST_CSV)
    (directory / 'notes.txt').write_text('shopping list')
    (directory / '.hidden.txt').write_text(LXCAT)
    return directory


def test_parse_lxcat() -> None:
    parsed = parse_lxcat(LXCAT)
    assert str(parsed.generated) == '2026-06-01'
    assert len(parsed.references) == 2
    assert [database.permlink for database in parsed.databases] == ['www.lxcat.net/Test-A', 'www.lxcat.net/Test-B']
    assert [process.type for process in parsed.processes] == ['ELASTIC', 'IONIZATION', 'Backscat']
    backscatter = parsed.processes[2]
    assert backscatter.target == 'Ar'
    assert backscatter.projectile == 'Ar^+'
    assert backscatter.comments == ['first comment', 'second comment']
    assert backscatter.data.shape == (2, 2)
    assert validate(parsed) == []


def test_lxcat_errors() -> None:
    with pytest.raises(ValueError, match='two columns'):
        parse_lxcat(LXCAT.replace(' 1.0e+1\t2.0e-20', ' 1.0e+1\t2.0e-20\t3.0'))
    with pytest.raises(ValueError, match='no numbers'):
        parse_lxcat(LXCAT.replace(' 1.0e+1\t2.0e-20', ' ten\ttwenty'))
    problems = validate(parse_lxcat(LXCAT.replace(' 1.0e+1\t2.0e-20', ' -1.0\t2.0e-20')))
    assert any('energies not increasing' in problem for problem in problems)


def test_parse_nist() -> None:
    levels = parse_nist_levels(NIST_CSV, name_hint='Ar_I_levels.csv')
    assert levels.unit == 'cm-1'
    assert levels.species == 'Ar'  # from the file name, not from the 'Ar II' limit row
    assert levels.levels.tolist() == [[1.0, 0.0], [5.0, 93000.0]]
    assert levels.skipped == 1 and levels.limit == pytest.approx(127109.842)
    text = parse_nist_levels(NIST_TEXT)
    assert text.limit is None
    assert (text.unit, text.species) == ('eV', 'ArIon1')
    assert text.levels[:, 0].tolist() == [4.0, 2.0]
    assert piclas_species('XeIon test Xe_III') == 'XeIon2'
    with pytest.raises(ValueError):
        parse_nist_levels('no table')


def test_identify(downloads: pathlib.Path) -> None:
    lxcat = identify(downloads / 'lxcat.txt')
    assert (lxcat.provider, lxcat.kind, lxcat.dataset) == ('lxcat', 'cross-sections', 'test-a+test-b/ar')
    assert str(lxcat.retrieved) == '2026-06-01'
    nist = identify(downloads / 'Ar_I_levels.csv')
    assert (nist.provider, nist.dataset, nist.species) == ('nist-asd', 'levels/ar', ['Ar'])
    assert identify(downloads / 'notes.txt', custom='My Data').dataset == 'my-data'
    with pytest.raises(IdentifyError, match='not recognized'):
        identify(downloads / 'notes.txt')
    (downloads / 'levels.csv').write_text(NIST_CSV)
    with pytest.raises(IdentifyError, match='--species'):
        identify(downloads / 'levels.csv')
    assert identify(downloads / 'levels.csv', species='Ar').species == ['Ar']
    (downloads / 'binary.h5').write_bytes(b'\x89HDF\r\n\x1a\n\x00\x00')
    with pytest.raises(IdentifyError, match='binary'):
        identify(downloads / 'binary.h5')
    assert database_slug('Biagi-v7.1 (Magboltz version 7.1)') == 'biagi-v7.1'
    assert database_slug('Phelps database') == 'phelps'


def test_import_and_store(downloads: pathlib.Path, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = tmp_path / 'store'
    assert main(['import', '--source-dir', str(downloads), '--store', str(store), '--dry-run']) == 0
    assert not store.exists()
    assert main(['import', '--source-dir', str(downloads), '--store', str(store), '--retrieved', '2026-11-17']) == 0
    output = capsys.readouterr().out
    assert '2 imported' in output and '1 skipped' in output  # notes.txt skipped, hidden file ignored

    entries = Store(store).entries()
    assert sorted(entry.relative.split('/')[0] for entry in entries) == ['lxcat', 'nist-asd']
    lxcat = next(entry for entry in entries if entry.meta['provider'] == 'lxcat')
    assert lxcat.path.read_text() == LXCAT  # byte for byte
    assert lxcat.meta['retrieved'] == '2026-11-17'
    assert lxcat.meta['processes'] == {'e / Ar: ELASTIC': 1, 'e / Ar: IONIZATION': 1, 'Ar^+ / Ar: Backscat': 1}
    index = yaml.safe_load((store / 'index.yaml').read_text())
    assert len(index['files']) == 2

    assert main(['import', str(downloads / 'lxcat.txt'), '--store', str(store)]) == 0
    assert 'already in the store' in capsys.readouterr().out
    assert main(['import', str(downloads / 'notes.txt'), '--store', str(store)]) == 1  # explicit unknown file is an error
    assert main(['import', str(downloads / 'notes.txt'), '--store', str(store), '--custom', 'own']) == 0
    assert main(['store', '--store', str(store)]) == 0
    assert main(['store', '--store', str(store), '--verify']) == 0
    lxcat.path.write_text(LXCAT + 'changed')
    assert main(['store', '--store', str(store), '--verify']) == 1
    assert 'sha256 mismatch' in capsys.readouterr().out


def test_import_errors(tmp_path: pathlib.Path) -> None:
    assert main(['import', '--store', str(tmp_path / 'store')]) == 1  # nothing given
    assert main(['import', '--source-dir', str(tmp_path / 'missing'), '--store', str(tmp_path / 'store')]) == 1
    assert main(['import', str(tmp_path / 'missing.txt'), '--store', str(tmp_path / 'store')]) == 1
    (tmp_path / 'a.txt').write_text(LXCAT)
    assert main(['import', str(tmp_path / 'a.txt'), '--retrieved', 'June', '--store', str(tmp_path / 'store')]) == 1


def test_default_store(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    monkeypatch.setenv('PICLAS_DB_STORE', str(tmp_path / 'env'))
    assert default_store() == tmp_path / 'env'
    monkeypatch.delenv('PICLAS_DB_STORE')
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'xdg'))
    assert default_store() == tmp_path / 'xdg' / 'piclas-db' / 'store'


# Both "Format output" variants of the ASD levels form, in their real structure (values invented)
NIST_ASCII_FORM = """--------------------------------------------------------------------------------------------------------------
Configuration          | Term      |   J |          Level (cm-1)   | Uncertainty (cm-1) |   Landé | Reference
-----------------------|-----------|-----|-------------------------|--------------------|---------|-----------
                       |           |     |                         |                    |         |
3s2.3p6                | 1S        |   0 |            0.0000       |             0      |         |     L0001
                       |           |     |                         |                    |         |
3s2.3p5.(2P*<3/2>).4s  | 2[3/2]*   |   2 |        90000.0000       |                    |   1.506 |
                       |           |   1 |        91000.0000       |                    |   1.404 |
                       |           |   3 |      [99000.5]          |                    |         |
Tx II (3p5 2P*<3/2>)   | Limit     | --- |       100000.000        |             0.004  |         |     L0002
                       |           |     |                         |                    |         |
3s.3p6.24p             | 1P*       |   1 |       150000.00         |                    |         |
--------------------------------------------------------------------------------------------------------------
"""
NIST_CSV_FORM = 'Configuration,Term,J,Prefix,Level (cm-1),Suffix,Uncertainty (cm-1),Lande,Reference\n' + ''.join(
    ','.join(f'"=""{value}"""' for value in row) + '\n'
    for row in (
        ('3s2.3p6', '1S', '0', '', '0.0000', '', '0', '', 'L0001'),
        ('3s2.3p5.(2P*<3/2>).4s', '2[3/2]*', '2', '', '90000.0000', '', '', '1.506', ''),
        ('3s2.3p5.(2P*<3/2>).4s', '2[3/2]*', '1', '', '91000.0000', '', '', '1.404', ''),
        ('3s2.3p5.(2P*<3/2>).4d', '2[7/2]', '3', '[', '99000.5', ']', '', '', ''),
        ('Tx II (3p5 2P*<3/2>)', 'Limit', '---', '', '100000.000', '', '0.004', '', 'L0002'),
        ('3s.3p6.24p', '1P*', '1', '', '150000.00', '', '', '', ''),
    )
)


def test_parse_nist_form_formats() -> None:
    """ASCII (text) and CSV (text): same levels, the limit (not a level), bracketed values counted, species from the file name"""
    ascii_, csv_ = parse_nist_levels(NIST_ASCII_FORM, 'NIST-Tx-I-ASCII.txt'), parse_nist_levels(NIST_CSV_FORM, 'NIST-Tx-I-CSV.csv')
    for parsed in (ascii_, csv_):
        assert parsed.species == 'Tx' and parsed.unit == 'cm-1' and parsed.limit == pytest.approx(100000.0)
        assert parsed.levels.tolist() == [[1.0, 0.0], [5.0, 90000.0], [3.0, 91000.0], [7.0, 99000.5], [3.0, 150000.0]]
    assert ascii_.estimated == csv_.estimated == 1  # '[99000.5]' in the column; the CSV writes the brackets into Prefix/Suffix
