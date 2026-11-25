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
"""Tables for an interactive terminal: box-drawing borders, columns fitted to the terminal width (long cells wrapped), groups of
rows separated by a thin line, optional colors. Output into a file or pipe stays plain text (see interactive())."""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import os
import shutil
import sys
import textwrap
from dataclasses import dataclass, field
from typing import Optional
# ==================================================================================================================================

# 'dim' is gray (bright black, 90) rather than the faint attribute (2), which some terminals and color schemes do not show
COLORS = {'red': '31', 'green': '32', 'yellow': '33', 'blue': '34', 'magenta': '35', 'cyan': '36', 'dim': '90', 'bold': '1'}
MIN_WIDTH = 8


def interactive() -> bool:
    """True if standard output is a terminal (not redirected into a file or pipe)"""
    return sys.stdout.isatty()


COLOR_MODE = {'mode': 'auto'}  # set by --color (auto, always, never)


def use_color() -> bool:
    """--color always/never; auto: on a terminal, not with NO_COLOR (https://no-color.org) or TERM=dumb; FORCE_COLOR or
    CLICOLOR_FORCE force colors also into a pipe (e.g. through tee or less -R)"""
    mode = COLOR_MODE['mode']
    if mode in ('always', 'never'):
        return mode == 'always'
    if 'NO_COLOR' in os.environ:
        return False
    if os.environ.get('FORCE_COLOR') or os.environ.get('CLICOLOR_FORCE', '0') != '0':
        return True
    return interactive() and os.environ.get('TERM') != 'dumb'


def paint(text: str, color: Optional[str], enabled: bool) -> str:
    return f'\033[{COLORS[color]}m{text}\033[0m' if enabled and color and text else text


@dataclass
class Row:
    cells: list[str]
    colors: list[Optional[str]] = field(default_factory=list)  # per cell, None: default
    group_start: bool = False  # thin separator line above this row


def fit_widths(natural: list[int], total: int, shrinkable: list[int]) -> list[int]:
    """Column widths: natural widths, reduced (widest first) until the table fits into total"""
    widths = list(natural)
    # first the shrinkable columns down to MIN_WIDTH, then (very narrow terminal) every column down to 3 characters
    for columns, smallest in ((shrinkable, MIN_WIDTH), (list(range(len(widths))), 3)):
        while sum(widths) > total:
            candidates = [index for index in columns if widths[index] > smallest]
            if not candidates:
                break
            widths[max(candidates, key=lambda index: widths[index])] -= 1
    return widths


def render(headers: list[str], rows: list[Row], width: Optional[int] = None, shrinkable: Optional[list[int]] = None, align_right: tuple[int, ...] = (), color: bool = False) -> list[str]:
    """Lines of a table with box-drawing borders; cells of the shrinkable columns are wrapped to fit the width"""
    columns = len(headers)
    width = width or shutil.get_terminal_size((120, 24)).columns
    natural = [max([len(header), *(len(row.cells[index]) for row in rows)]) for index, header in enumerate(headers)]
    widths = fit_widths(natural, width - (3 * columns + 1), list(range(columns)) if shrinkable is None else shrinkable)

    def border(left: str, middle: str, right: str, line: str = '─') -> str:
        return paint(left + middle.join(line * (size + 2) for size in widths) + right, 'dim', color)

    def lines_of(cells: list[str], colors: list[Optional[str]], bold: bool = False) -> list[str]:
        wrapped = [textwrap.wrap(cell, size, break_long_words=True, break_on_hyphens=False) or [''] for cell, size in zip(cells, widths, strict=True)]
        out = []
        for line in range(max(len(parts) for parts in wrapped)):
            texts = []
            for index, parts in enumerate(wrapped):
                text = parts[line] if line < len(parts) else ''
                text = text.rjust(widths[index]) if index in align_right else text.ljust(widths[index])
                texts.append(paint(text, 'bold' if bold else (colors[index] if index < len(colors) else None), color))
            bar = paint('│', 'dim', color)
            out.append(f'{bar} ' + f' {bar} '.join(texts) + f' {bar}')
        return out

    lines = [border('┌', '┬', '┐'), *lines_of(headers, [], bold=True), border('├', '┼', '┤')]
    for number, row in enumerate(rows):
        if row.group_start and number:
            lines.append(border('├', '┼', '┤', '┄'))
        lines += lines_of(row.cells, row.colors)
    lines.append(border('└', '┴', '┘'))
    return lines
