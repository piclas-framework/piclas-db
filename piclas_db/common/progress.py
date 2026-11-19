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
"""Progress of slow steps (downloads, git operations): a spinner with elapsed time on a terminal, plain lines otherwise"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import sys
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
# ==================================================================================================================================

FRAMES = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'


@contextmanager
def progress(label: str, interval: float = 0.1) -> Generator[None]:
    """'  <label> ⠋ 2.3 s' while the block runs (terminal), then '  <label> done (2.3 s)' or '... failed (2.3 s)'.
    Output that is not a terminal (logs, pipes, tests) gets one line at the end, without animation."""
    start = time.monotonic()
    animate = sys.stdout.isatty()
    stop = threading.Event()

    def spin() -> None:
        frame = 0
        while not stop.wait(interval):
            sys.stdout.write(f'\r  {label} {FRAMES[frame % len(FRAMES)]} {time.monotonic() - start:5.1f} s')
            sys.stdout.flush()
            frame += 1

    thread = threading.Thread(target=spin, daemon=True) if animate else None
    if thread is not None:
        thread.start()
    outcome = 'done'
    try:
        yield
    except BaseException:
        outcome = 'failed'
        raise
    finally:
        stop.set()
        if thread is not None:
            thread.join()
            sys.stdout.write('\r\033[K')  # clear the spinner line
        print(f'  {label} {outcome} ({time.monotonic() - start:.1f} s)', flush=True)
