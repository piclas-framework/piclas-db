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

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.compare import compare
from piclas_db.readers import DatabaseReadError
from piclas_db.sources.any import read_any
# ==================================================================================================================================


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
    for difference in comparison.differences:
        source = ' [different source]' if difference.different_source else ''
        print(f'{difference.change.value:22s} {difference.path}: {difference.message}{source}')
    counts = Counter(difference.change.value for difference in comparison.differences)
    summary = ', '.join(f'{count} {change}' for change, count in sorted(counts.items()))
    print(f'\n{comparison.identical} identical' + (f', {summary}' if summary else ''))
    return 0 if comparison.equal else 1
