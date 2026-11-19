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
import datetime
import pathlib

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.common.common_vars import Common
from piclas_db.model import Database
from piclas_db.readers import DatabaseReadError, read_database
from piclas_db.sources.own import OwnDataError, dump_own_data, own_data_from_database
from piclas_db.store import sha256
from piclas_db.tables import TablesError, export_tables
# ==================================================================================================================================


def export_own_data(database: Database, args: argparse.Namespace) -> int:
    """Species attributes of a database as an own-data file, every species with a Reference"""
    source, target = pathlib.Path(args.source), pathlib.Path(args.own_data)
    if target.exists() and not args.force:
        print(f'ERROR: {target} exists (use --force to overwrite)')
        return 1
    origin = args.origin or f'{source.name} ({datetime.date.fromtimestamp(source.stat().st_mtime).isoformat()})'
    export = own_data_from_database(database, origin, name=args.name, keep_atct=args.keep_atct)
    if not export.content['species']:
        print(f'ERROR: {source}: no species attributes')
        return 1
    header = [
        f'Own data written by piclas-db {Common().version} on {datetime.date.today().isoformat()} from {source.name}',
        f'(sha256 {sha256(source)}). Check every Reference and replace "source unknown" where the source is found, then import',
        f'the file into the store (piclas-db import {target.name}) and use it in a recipe with "own_data: own/{args.name}".',
    ]
    if export.left_out:
        header += ['', f'Left out (the file credits them to ATcT, a recipe takes them from ATcT with "atct: <ID>"): {", ".join(sorted(export.left_out))}']
    header += ['Electronic and vibrational levels are not own data (recipe "levels", NIST ASD).']
    try:
        text = dump_own_data(export.content, header)
    except OwnDataError as e:
        print(f'ERROR: {e}')
        return 1
    target.write_text(text, encoding='utf-8')
    unknown = sum(len(attributes) for attributes in export.unknown.values())
    print(f'{source} -> {target}: {len(export.content["species"])} species, origin "{origin}"')
    if export.left_out:
        print(f'  ATcT ({len(export.left_out)} species): {", ".join(sorted({key for keys in export.left_out.values() for key in keys}))} left out (use --keep-atct to keep them)')
    elif export.atct_species:
        print(f'  ATcT ({len(export.atct_species)} species): values kept (--keep-atct)')
    print(f'  source unknown: {unknown} values in {len(export.unknown)} species (see the Reference of each species)')
    return 0


def run(args: argparse.Namespace) -> int:
    """Write a database of any layout as ASCII tables into a new or empty directory, and/or its species as an own-data file"""
    if not args.output and not args.own_data:
        print('ERROR: give a directory for the tables with -o and/or an own-data file with --own-data')
        return 1
    try:
        database = read_database(args.source)
        if args.output:
            export_tables(database, args.output)
    except (DatabaseReadError, TablesError) as e:
        print(f'ERROR: {e}')
        return 1
    if args.output:
        summary = ', '.join(f'{count} {name}' for name, count in database.summary().items() if count)
        print(f'{args.source} -> {args.output}: {summary}')
        print(f'Convert back with: piclas-db migrate {args.output} -o <file>.h5')
    return export_own_data(database, args) if args.own_data else 0
