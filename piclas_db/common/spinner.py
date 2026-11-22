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
"""Progress of a loop over many items on a terminal (progress.py: single slow steps): a bar with counter and a spinner while a slow step runs (e.g. Crossref lookups), drawn on stderr and
cleared before the next output line; nothing at all when stderr is not a terminal (redirected output stays clean)"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import shutil
import sys
import threading
from collections.abc import Generator
from contextlib import contextmanager
from typing import Optional
# ==================================================================================================================================

FRAMES = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
BAR = 20


class Progress:
    def __init__(self, total: int, enabled: Optional[bool] = None) -> None:
        self.total = total
        self.enabled = sys.stderr.isatty() if enabled is None else enabled
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._line = ''

    def line(self, done: int, frame: str, text: str) -> str:
        filled = round(BAR * done / self.total) if self.total else BAR
        head = f'{frame} [{"█" * filled}{"░" * (BAR - filled)}] {done}/{self.total} {100 * done // max(self.total, 1):3d}% '
        width = shutil.get_terminal_size((100, 20)).columns
        return (head + text)[: max(width - 1, len(head))]

    def _spin(self, done: int, text: str) -> None:
        index = 0
        while not self._stop.is_set():
            self._line = self.line(done, FRAMES[index % len(FRAMES)], text)
            sys.stderr.write('\r\033[K' + self._line)
            sys.stderr.flush()
            index += 1
            self._stop.wait(0.1)

    @contextmanager
    def step(self, done: int, text: str) -> Generator[None]:
        """Spinner with the bar at 'done' finished items while the block runs; the line is cleared afterwards"""
        if not self.enabled:
            yield
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._spin, args=(done, text), daemon=True)
        self._thread.start()
        try:
            yield
        finally:
            self._stop.set()
            self._thread.join()
            self.clear()

    def clear(self) -> None:
        if self.enabled:
            sys.stderr.write('\r\033[K')
            sys.stderr.flush()
