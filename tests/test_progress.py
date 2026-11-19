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
import sys
import time

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import pytest

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.common.progress import progress
# ==================================================================================================================================


def test_plain_output(capsys: pytest.CaptureFixture[str]) -> None:
    with progress('downloading x'):
        pass
    out = capsys.readouterr().out
    assert out.startswith('  downloading x done (') and out.rstrip().endswith(' s)') and '\r' not in out  # no animation in logs
    with pytest.raises(ValueError), progress('downloading y'):
        raise ValueError
    assert 'downloading y failed' in capsys.readouterr().out


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_spinner_on_a_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    terminal = Terminal()
    monkeypatch.setattr(sys, 'stdout', terminal)
    with progress('downloading z', interval=0.01):
        time.sleep(0.08)
    text = terminal.getvalue()
    assert '\r  downloading z ' in text and ' s' in text  # spinner frames with elapsed time
    assert text.rstrip().split('\r')[-1].endswith(' s)') and 'downloading z done' in text  # final line replaces the spinner
