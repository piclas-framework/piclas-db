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
from piclas_db.commands import COMMANDS
from piclas_db.common.common_vars import Common
# ==================================================================================================================================


def build_parser() -> argparse.ArgumentParser:
    """Command-line interface: one sub-command per task"""
    common = Common()
    parser = argparse.ArgumentParser(
        prog=common.program,
        description='Build, check and convert PICLas species and cross-section databases (database.h5) from original sources such as LXCat and NIST.',
        epilog=f'Run "{common.program} <command> --help" for the options of a command.',
    )
    parser.add_argument('-v', '--version', action='version', version=common.version_string())

    subparsers = parser.add_subparsers(dest='command', metavar='<command>')
    for name, command in COMMANDS.items():
        sub = subparsers.add_parser(name, help=command.help, description=command.help)
        if name == 'check':
            sub.add_argument('file', help='database file (.h5) to check')
            sub.add_argument('--info', action='store_true', help='also show findings of severity INFO')
            sub.add_argument('--json', action='store_true', help='print the findings as JSON')
        elif name == 'import':
            sub.add_argument('files', nargs='*', help='downloaded files (LXCat, NIST ASD, ...)')
            sub.add_argument('--source-dir', help='directory to search for downloaded files (e.g. ~/Downloads); unknown files are skipped')
            sub.add_argument('--store', help='local store (default: $PICLAS_DB_STORE or ~/.local/share/piclas-db/store)')
            sub.add_argument('--species', help='species of a NIST ASD level file if not found in the file or its name (e.g. ArIon1)')
            sub.add_argument('--custom', metavar='NAME', help='store files that are not recognized (e.g. own data) under custom/NAME')
            sub.add_argument('--retrieved', metavar='YYYY-MM-DD', help='retrieval date if not contained in the file')
            sub.add_argument('--dry-run', action='store_true', help='only show what would be imported')
        elif name == 'fetch':
            sub.add_argument('--mirror', help='private repository (git URL, e.g. git@github.com:<org>/<repo>.git; default: $PICLAS_DB_MIRROR)')
            sub.add_argument('--need', nargs='+', default=[], metavar='PROVIDER/DATASET[@SHA]', help='locate these original files')
            sub.add_argument('--store', help='local store (default: $PICLAS_DB_STORE or ~/.local/share/piclas-db/store)')
        elif name == 'push':
            sub.add_argument('--store', help='local store (default: $PICLAS_DB_STORE or ~/.local/share/piclas-db/store)')
        elif name == 'store':
            sub.add_argument('--store', help='local store (default: $PICLAS_DB_STORE or ~/.local/share/piclas-db/store)')
            sub.add_argument('--verify', action='store_true', help='check that every file still matches its sha256')
        elif name == 'export':
            sub.add_argument('source', help='database file (.h5) of any layout')
            sub.add_argument('-o', '--output', required=True, help='new or empty directory for the tables')
        elif name == 'migrate':
            sub.add_argument('source', help='database file (.h5) of any layout, or a directory with ASCII tables')
            sub.add_argument('-o', '--output', required=True, help='new database file (.h5)')
            sub.add_argument('--fix', action='store_true', help='rename typos in group and attribute names, sort electronic levels')
            sub.add_argument('--canonical-products', action='store_true', help='rename reaction cross-sections to heavy species first, electrons last')
            sub.add_argument('--force', action='store_true', help='overwrite an existing output file')
        elif name == 'diff':
            sub.add_argument('a', help='first database file (A)')
            sub.add_argument('b', help='second database file (B)')
            sub.add_argument('--rtol', type=float, default=1.0e-6, help='relative tolerance for identical values (default: 1e-6, covers float32)')
            sub.add_argument('--all', action='store_true', help='also report categories that exist in only one of the files')
            sub.add_argument('--json', action='store_true', help='print the differences as JSON')

    return parser
