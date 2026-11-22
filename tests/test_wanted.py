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
"""Wanted literature: literature want/wanted/unwant, the line in piclas-db store, removal on import (invented papers)"""

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
from piclas_db import wanted
from piclas_db.piclas_db import main
from piclas_db.store import Store
# ==================================================================================================================================

PDF = b'%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n'


def test_wanted_list(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv('PICLAS_DB_STORE', str(tmp_path / 'store'))
    store = Store(tmp_path / 'store')
    assert main(['literature', 'wanted']) == 0
    assert 'No papers wanted' in capsys.readouterr().out
    assert main(['literature', 'want', 'author-1990', '--reference', 'A. Author, A Book, Publisher, 1990', '--needed-for', 'rate table p. 3']) == 0
    assert main(['literature', 'want', 'other-1987', '--reference', 'B. Other, J. Test 20:1, 1987', '--doi', '10.0000/other', '--note', 'publisher gave the wrong file']) == 0
    assert main(['literature', 'want', 'other-1987', '--reference', 'B. Other, J. Test 20:1, 1987', '--note', 'second try failed too']) == 0  # update
    capsys.readouterr()
    entries = wanted.load(store)
    assert sorted(entries) == ['author-1990', 'other-1987'] and entries['other-1987']['notes'] == ['publisher gave the wrong file', 'second try failed too']
    assert entries['author-1990']['by'] == 'piclas-db test <test@example.com>'
    assert main(['literature', 'wanted']) == 0
    out = capsys.readouterr().out
    assert 'https://doi.org/10.0000/other' in out and 'needed for: rate table p. 3' in out
    assert main(['store']) == 0
    assert '2 paper(s) wanted: author-1990, other-1987' in capsys.readouterr().out
    # importing the paper with its DOI (under another key) removes its entry
    (tmp_path / 'paper.pdf').write_bytes(PDF)
    assert main(['import', str(tmp_path / 'paper.pdf'), '--literature', 'other-1987b', '--doi', '10.0000/other', '--reference', 'B. Other 1987']) == 0
    assert 'WANTED other-1987: no longer wanted' in capsys.readouterr().out
    assert list(wanted.load(store)) == ['author-1990']
    assert main(['literature', 'want', 'other-1987b', '--reference', 'x']) == 1  # already in the store
    assert 'already in the store' in capsys.readouterr().out
    assert main(['literature', 'unwant', 'author-1990']) == 0
    assert not (tmp_path / 'store' / wanted.FILE).exists()
    assert main(['literature', 'unwant', 'author-1990']) == 1
