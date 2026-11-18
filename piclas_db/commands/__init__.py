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
from piclas_db.commands import build, check, diff, export, extract, fetch, guide, import_, literature, migrate, plot, push, rebuild, reservoir, store
# ==================================================================================================================================


@dataclass(frozen=True)
class Command:
    """Sub-command of the command-line tool"""

    help: str  # one-line description shown by --help
    work_package: str  # work package of the project plan in which the command is implemented
    run: Callable[[argparse.Namespace], int]  # function executing the command, returns the exit code


# Order defines the order in the --help output
COMMANDS: dict[str, Command] = {
    # Data acquisition and build
    'guide':     Command('Step-by-step download instructions for original files or for the missing files of a recipe', 'WP1', guide.run),
    'import':    Command('Identify downloaded files by content, validate and copy them into the local store', 'WP1', import_.run),
    'fetch':     Command('Clone or update the local store from the private repository; --need locates required files', 'WP1', fetch.run),
    'push':      Command('Back up the local store to the private repository', 'WP1', push.run),
    'store':     Command('List the local store or verify its files (--verify)', 'WP1', store.run),
    'literature': Command('Data from papers: templates for entering tables, store extractions with their record, review them', 'WP1', literature.run),
    'extract':   Command('Extract the data series of a vector figure of a paper into extraction records', 'WP1', extract.run),
    'build':     Command('Build a database from the original files in the store according to a recipe', 'WP1', build.run),
    # Conversion, visualization and validation
    'export':    Command('Write a database of any layout as ASCII tables (YAML and CSV)', 'WP2', export.run),
    'plot':      Command('Plot cross-sections, rate coefficients or electronic levels from any source, also in comparison', 'WP3', plot.run),
    'reservoir': Command('Generate a PICLas reservoir study (parameter.ini files) or evaluate it against the database', 'WP4', reservoir.run),
    # Analysis of existing (also old) database files
    'check':     Command('Detect the layout of a database file and report corrupt or inconsistent data', 'WP2', check.run),
    'diff':      Command('Compare two databases of any layout: changed datasets and attributes, and by how much', 'WP2', diff.run),
    'migrate':   Command('Convert a database (any layout or ASCII tables) to the current layout (writes a new file)', 'WP2', migrate.run),
    'rebuild':   Command('Rebuild an existing database from the original files and compare it with the original', 'WP2', rebuild.run),
}  # fmt: skip
