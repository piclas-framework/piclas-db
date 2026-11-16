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
import sys
from typing import Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.args_parser import build_parser
from piclas_db.commands import COMMANDS, not_implemented
# ==================================================================================================================================


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point of the piclas-db command-line tool, returns the exit code"""
    parser = build_parser()
    # Planned commands accept any arguments until they are implemented, implemented commands reject unknown arguments
    args, unknown = parser.parse_known_args(argv)
    if unknown and (args.command is None or COMMANDS[args.command].run is not not_implemented):
        parser.error(f'unrecognized arguments: {" ".join(unknown)}')

    # No command given: show the help
    if args.command is None:
        parser.print_help()
        return 0

    return COMMANDS[args.command].run(args)


def entry_point() -> None:
    """Console script entry point (pyproject.toml), passes the exit code to the shell"""
    sys.exit(main())


if __name__ == '__main__':
    entry_point()
