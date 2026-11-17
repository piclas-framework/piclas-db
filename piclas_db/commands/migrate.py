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
import pathlib
from collections import Counter

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.migrate import migrate
from piclas_db.readers import DatabaseReadError, read_database
from piclas_db.rules import Severity, run_checks
from piclas_db.writer import write_database
# ==================================================================================================================================


def run(args: argparse.Namespace) -> int:
    """Convert a database (any layout or ASCII tables) into the current layout; always writes a new file"""
    source, output = pathlib.Path(args.source), pathlib.Path(args.output)
    if output.exists() and output.resolve() == source.resolve():
        print('ERROR: the output must not be the input file')
        return 1
    if output.exists() and not args.force:
        print(f'ERROR: {output} exists (use --force to overwrite)')
        return 1
    try:
        database = read_database(source)
    except DatabaseReadError as e:
        print(f'ERROR: {e}')
        return 1

    report = migrate(database, fix=args.fix, products=args.canonical_products)
    write_database(database, output)

    print(f'{source} ({database.schema.value}) -> {output} (species database layout)')
    for title, lines in (('Normalized', report.normalized), ('Fixed', report.fixed), ('Not fixed', report.skipped), ('Note', report.notes)):
        for line in lines:
            print(f'  {title + ":":11s} {line}')

    findings = run_checks(read_database(output))
    counts = Counter(finding.severity for finding in findings)
    print(f'Check of {output}: {counts[Severity.ERROR]} error(s), {counts[Severity.WARNING]} warning(s) (details: piclas-db check {output})')
    if not args.fix and counts[Severity.ERROR]:
        print('Some errors can be corrected with --fix')
    return 0
