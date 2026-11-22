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
"""Progress bar with spinner (import --literature) and the color modes (--color, NO_COLOR, FORCE_COLOR)"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import time

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import pytest

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.common import table
from piclas_db.common.spinner import Progress
# ==================================================================================================================================


def test_progress_bar(capsys: pytest.CaptureFixture[str]) -> None:
    progress = Progress(4, enabled=True)
    assert progress.line(1, '⠋', 'paper.pdf').startswith('⠋ [█████░░░░░░░░░░░░░░░] 1/4  25% paper.pdf')
    with progress.step(2, 'slow.pdf'):
        time.sleep(0.25)
    err = capsys.readouterr().err
    assert '2/4  50% slow.pdf' in err and err.endswith('\r\033[K')  # drawn while running, cleared afterwards
    with Progress(4, enabled=False).step(0, 'quiet.pdf'):  # not a terminal: nothing at all
        pass
    assert capsys.readouterr().err == ''


def test_color_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(table, 'interactive', lambda: False)
    monkeypatch.delenv('NO_COLOR', raising=False)
    monkeypatch.delenv('FORCE_COLOR', raising=False)
    monkeypatch.delenv('CLICOLOR_FORCE', raising=False)
    monkeypatch.setitem(table.COLOR_MODE, 'mode', 'auto')
    assert not table.use_color()  # a pipe
    monkeypatch.setenv('FORCE_COLOR', '1')
    assert table.use_color()
    monkeypatch.setenv('NO_COLOR', '1')
    assert not table.use_color()  # NO_COLOR wins over FORCE_COLOR
    monkeypatch.setitem(table.COLOR_MODE, 'mode', 'always')
    assert table.use_color()  # the command line wins over both
    monkeypatch.setitem(table.COLOR_MODE, 'mode', 'never')
    monkeypatch.delenv('NO_COLOR')
    assert not table.use_color()
