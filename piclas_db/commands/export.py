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
from piclas_db.tables import TablesError, export_tables
# ==================================================================================================================================


def run(args: argparse.Namespace) -> int:
    """Write a database of any layout as ASCII tables into a new or empty directory"""
    try:
        database = read_database(args.source)
        export_tables(database, args.output)
    except (DatabaseReadError, TablesError) as e:
        print(f'ERROR: {e}')
        return 1
    summary = ', '.join(f'{count} {name}' for name, count in database.summary().items() if count)
    print(f'{args.source} -> {args.output}: {summary}')
    print(f'Convert back with: piclas-db migrate {args.output} -o <file>.h5')
    return 0
