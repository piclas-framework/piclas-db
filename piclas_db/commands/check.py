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

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.readers import DatabaseReadError, read_database
from piclas_db.schema import Schema
# ==================================================================================================================================


def run(args: argparse.Namespace) -> int:
    """Check a database file: layout detection, complete read-in and summary (rules for the content follow in later versions)"""
    try:
        database = read_database(args.file)
    except DatabaseReadError as e:
        print(f'ERROR: {e}')
        return 1

    print(f'File:   {database.path}')
    print(f'Layout: {database.schema.value}')
    for category, count in database.summary().items():
        if count:
            print(f'  {category:22s} {count}')

    for name in database.unreadable:
        print(f'ERROR: dataset cannot be read: {name}')

    errors = len(database.unreadable) + (1 if database.schema is Schema.UNKNOWN else 0)
    print(f'{errors} error(s)')
    return 1 if errors else 0
