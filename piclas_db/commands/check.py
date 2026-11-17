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
from piclas_db import provenance
from piclas_db.readers import DatabaseReadError, read_database
from piclas_db.rules import Severity, run_checks
# ==================================================================================================================================


def run(args: argparse.Namespace) -> int:
    """Check a database file: layout detection, complete read-in and all content rules; exit code 1 if errors are found"""
    try:
        database = read_database(args.file)
    except DatabaseReadError as e:
        print(f'ERROR: {e}')
        return 1

    findings = run_checks(database)
    shown = findings if args.info else [finding for finding in findings if finding.severity is not Severity.INFO]
    counts = Counter(finding.severity for finding in findings)

    if args.json:
        print(json.dumps({'file': database.path, 'layout': database.schema.value, 'findings': [finding.as_dict() for finding in shown]}, indent=2))
    else:
        print(f'File:   {database.path}')
        print(f'Layout: {database.schema.value}')
        record = provenance.read(database.attributes)
        if record.present:
            print(f'Made:   piclas-db {record.version} (commit {record.commit}), {record.created}: {record.command}')
            details = [f'{len(record.sources)} original file(s)'] + (['recipe embedded'] if record.recipe else []) + ([f'input {record.input}'] if record.input else [])
            print(f'        {"; ".join(details)}')
        for category, count in database.summary().items():
            if count:
                print(f'  {category:22s} {count}')
        if shown:
            print()
        for finding in shown:
            print(f'{finding.severity.value:7s} {finding.path}: {finding.message} [{finding.rule}]')
        print(f'\n{counts[Severity.ERROR]} error(s), {counts[Severity.WARNING]} warning(s), {counts[Severity.INFO]} info' + ('' if args.info else ' (show with --info)'))

    return 1 if counts[Severity.ERROR] else 0
