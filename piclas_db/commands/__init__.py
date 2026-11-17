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
from collections.abc import Callable
from dataclasses import dataclass

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.commands import check, diff, export, migrate
# ==================================================================================================================================


@dataclass(frozen=True)
class Command:
    """Sub-command of the command-line tool"""

    help: str  # one-line description shown by --help
    work_package: str  # work package of the project plan in which the command is implemented
    run: Callable[[argparse.Namespace], int]  # function executing the command, returns the exit code


def not_implemented(args: argparse.Namespace) -> int:
    """Placeholder for commands that are planned but not implemented yet"""
    command = COMMANDS[args.command]
    print(f'{args.command}: not implemented yet (planned in {command.work_package})')
    return 1


# Order defines the order in the --help output
COMMANDS: dict[str, Command] = {
    # Data acquisition and build
    'guide':     Command('Step-by-step guide for a manual download of a dataset', 'WP1', not_implemented),
    'import':    Command('Identify downloaded files by content, validate and sort them into the local store', 'WP1', not_implemented),
    'fetch':     Command('Download data where the source terms allow it, or restore the local store from a private mirror', 'WP1', not_implemented),
    'push':      Command('Back up the local store to the private mirror repository', 'WP1', not_implemented),
    'build':     Command('Build database.h5 from the local store', 'WP1', not_implemented),
    # Conversion, visualization and validation
    'export':    Command('Write a database of any layout as ASCII tables (YAML and CSV)', 'WP2', export.run),
    'plot':      Command('Plot data from original files, ASCII tables or database.h5', 'WP3', not_implemented),
    'reservoir': Command('Create parameter.ini files for a reservoir parameter study', 'WP4', not_implemented),
    # Analysis of existing (also old) database files
    'check':     Command('Detect the layout of a database file and report corrupt or inconsistent data', 'WP2', check.run),
    'diff':      Command('Compare two databases of any layout: changed datasets and attributes, and by how much', 'WP2', diff.run),
    'migrate':   Command('Convert a database (any layout or ASCII tables) to the current layout (writes a new file)', 'WP2', migrate.run),
    'rebuild':   Command('Rebuild an existing database from re-downloaded original sources and compare it with the original', 'WP2', not_implemented),
}  # fmt: skip
