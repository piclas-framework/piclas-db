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

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import h5py

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.schema import Schema, detect_schema
# ==================================================================================================================================


def read_all_datasets(h5: h5py.File) -> list[str]:
    """Read every dataset completely, return the paths of datasets that cannot be read (e.g. corrupt chunks)"""
    unreadable: list[str] = []

    def visit(name: str, obj: object) -> None:
        if isinstance(obj, h5py.Dataset):
            try:
                obj[()]
            except (OSError, ValueError, KeyError):
                unreadable.append(name)

    h5.visititems(visit)
    return unreadable


def run(args: argparse.Namespace) -> int:
    """Check a database file: file integrity and layout detection (further checks follow in later versions)"""
    path = pathlib.Path(args.file)
    if not path.is_file():
        print(f'ERROR: file not found: {path}')
        return 1

    try:
        h5 = h5py.File(path, 'r')
    except OSError as e:
        print(f'ERROR: cannot open {path} as HDF5 file: {e}')
        return 1

    with h5:
        schema = detect_schema(h5)
        print(f'File:   {path}')
        print(f'Layout: {schema.value}')
        unreadable = read_all_datasets(h5)

    for name in unreadable:
        print(f'ERROR: dataset cannot be read: {name}')

    errors = len(unreadable) + (1 if schema is Schema.UNKNOWN else 0)
    print(f'{errors} error(s)')
    return 1 if errors else 0
