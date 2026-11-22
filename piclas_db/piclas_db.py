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
import os
import sys
from typing import Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.args_parser import build_parser
from piclas_db import config
from piclas_db.commands import COMMANDS
from piclas_db.common import table
from piclas_db.store import missing_store, store_location
# ==================================================================================================================================


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point of the piclas-db command-line tool, returns the exit code"""
    parser = build_parser()
    args = parser.parse_args(argv)

    # No command given: show the help
    if args.command is None:
        parser.print_help()
        return 0

    # Defaults from the configuration file for options not given on the command line
    try:
        for warning in config.apply(args, subparsers(parser)[args.command]):
            print(f'WARNING: {warning}', file=sys.stderr)
    except config.ConfigError as e:
        print(f'ERROR: {e}')
        return 1

    if getattr(args, 'color', None):
        table.COLOR_MODE['mode'] = args.color

    # A store that was set explicitly but does not exist (deleted, moved, unmounted, or new): commands that only read it stop with
    # instructions; commands that add data create it with a warning; fetch may clone into it
    if hasattr(args, 'store') and args.command != 'fetch':
        problem = missing_store(args.store)
        if problem and getattr(args, 'dry_run', False):
            pass  # a dry run changes nothing, also not the store
        elif problem and adds_data(args):
            path, origin = store_location(args.store)
            print(f'WARNING: the store {path} (set by {origin}) did not exist: created as a new, empty store, not connected to a private repository', file=sys.stderr)
            path.mkdir(parents=True)
        elif problem:
            print(f'ERROR: {problem}')
            return 1
    return COMMANDS[args.command].run(args)


def adds_data(args: argparse.Namespace) -> bool:
    """Commands that put files into the store (and may create it)"""
    return args.command in ('import', 'extract', 'atct') or (args.command == 'literature' and getattr(args, 'action', None) in ('add', 'want'))


def subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    """Sub-parser of every command (to tell options given on the command line from defaults)"""
    for action in parser._actions:  # noqa: SLF001
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            choices = dict(action.choices)
            for sub in choices.values():
                sub._piclas_db_commands = tuple(choices)  # type: ignore[attr-defined]  # noqa: SLF001
            return choices
    return {}


def entry_point() -> None:
    """Console script entry point (pyproject.toml), passes the exit code to the shell"""
    try:
        code = main()
        sys.stdout.flush()
    except BrokenPipeError:
        # output piped into a program that stopped reading (e.g. 'piclas-db check file.h5 | head'): not an error
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        code = 0
    sys.exit(code)


if __name__ == '__main__':
    entry_point()
