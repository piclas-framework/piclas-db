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
import sys
from typing import Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.args_parser import build_parser
from piclas_db import config
from piclas_db.commands import COMMANDS
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
    return COMMANDS[args.command].run(args)


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
    sys.exit(main())


if __name__ == '__main__':
    entry_point()
