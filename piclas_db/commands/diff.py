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
import argparse
import json
from collections import Counter
from typing import Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.common.table import Row, interactive, paint, render, use_color
from piclas_db.compare import Change, Difference, compare
from piclas_db.readers import DatabaseReadError
from piclas_db.sources.any import read_any
# ==================================================================================================================================


CHANGE_COLORS = {
    Change.ONLY_IN_A: 'red',
    Change.ONLY_IN_B: 'green',
    Change.NUMERIC: 'yellow',
    Change.SCALED: 'yellow',
    Change.STRUCTURE: 'magenta',
    Change.ATTRIBUTE: 'cyan',
    Change.RENAMED: 'blue',
}
CHANGE_SHORT = {
    Change.ONLY_IN_A: 'only in A',
    Change.ONLY_IN_B: 'only in B',
    Change.NUMERIC: 'numeric',
    Change.SCALED: 'scaled',
    Change.STRUCTURE: 'structure',
    Change.ATTRIBUTE: 'attribute',
    Change.RENAMED: 'renamed',
}


def split_path(difference: Difference) -> tuple[str, str, str]:
    """Section, object and item of a difference: /Species/Ar/ElectronicLevel -> ('Species', 'Ar', 'ElectronicLevel')"""
    parts = difference.path.strip('/').split('/')
    section, name = parts[0], parts[1] if len(parts) > 1 else ''
    item = difference.item or '/'.join(parts[2:])
    return section, name, item


def table_lines(differences: list[Difference], color: bool = False, width: Optional[int] = None) -> list[str]:
    """Differences as one table per section (Species, Cross-Sections, Reactions, ...), rows grouped by object"""
    sections: dict[str, list[Difference]] = {}
    for difference in differences:
        sections.setdefault(split_path(difference)[0], []).append(difference)
    lines: list[str] = []
    for section, entries in sections.items():
        sizes: dict[str, int] = {}
        for difference in entries:
            sizes[split_path(difference)[1]] = sizes.get(split_path(difference)[1], 0) + 1
        rows, previous = [], None
        for difference in entries:
            _, name, item = split_path(difference)
            structured = bool(difference.value_a or difference.value_b)
            relative = f'{difference.relative:+.2e}' if difference.relative is not None else ''
            source = ' [different source]' if difference.different_source else ''
            cells = [
                name if name != previous else '',
                item,
                'only in A' if difference.value_b == '-' else 'only in B' if difference.value_a == '-' else CHANGE_SHORT[difference.change],
                (difference.value_a if structured else difference.message) + ('' if structured else source),
                difference.value_b if structured else '',
                relative,
            ]
            # a separator only around objects with several rows: single-row objects stay compact
            separate = name != previous and (sizes[name] > 1 or (previous is not None and sizes[previous] > 1))
            rows.append(Row(cells, colors=['bold' if name != previous else None, None, CHANGE_COLORS[difference.change]], group_start=separate))
            previous = name
        if lines:
            lines.append('')
        lines.append(paint(f'{section} ({len(entries)})', 'bold', color))
        lines += render(['Name', 'Item', 'Change', 'A', 'B', 'B/A - 1'], rows, width=width, shrinkable=[0, 1, 3, 4], align_right=(5,), color=color)
    return lines


def run(args: argparse.Namespace) -> int:
    """Compare two databases of any layout; exit code 0 if they are equal, 1 if they differ, 2 on read errors"""
    try:
        a, b = read_any(args.a), read_any(args.b)
    except DatabaseReadError as e:
        print(f'ERROR: {e}')
        return 2

    comparison = compare(a, b, rtol=args.rtol, everything=args.all)
    if args.json:
        print(
            json.dumps(
                {'a': a.path, 'b': b.path, 'compared': comparison.compared, 'skipped': comparison.skipped, 'identical': comparison.identical, 'differences': [d.as_dict() for d in comparison.differences]}, indent=2
            )
        )
        return 0 if comparison.equal else 1

    print(f'A: {a.path} ({a.schema.value})')
    print(f'B: {b.path} ({b.schema.value})')
    print(f'Compared: {", ".join(comparison.compared) or "nothing"}' + (f'; not compared: {", ".join(comparison.skipped)} (use --all)' if comparison.skipped else ''))
    if comparison.differences:
        print()
    if comparison.differences and interactive():
        print('\n'.join(table_lines(comparison.differences, color=use_color())))
    for difference in [] if interactive() else comparison.differences:
        source = ' [different source]' if difference.different_source else ''
        print(f'{difference.change.value:22s} {difference.path}: {difference.message}{source}')
    counts = Counter(difference.change.value for difference in comparison.differences)
    summary = ', '.join(f'{count} {change}' for change, count in sorted(counts.items()))
    print(f'\n{comparison.identical} identical' + (f', {summary}' if summary else ''))
    return 0 if comparison.equal else 1
