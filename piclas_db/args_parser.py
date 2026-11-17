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
