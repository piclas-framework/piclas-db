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
from piclas_db.store import Store
# ==================================================================================================================================


def run(args: argparse.Namespace) -> int:
    """List the local store, or verify that every file still matches its sha256"""
    store = Store(args.store)
    entries = store.entries()
    print(f'Store: {store.root} ({len(entries)} file(s))')
    if args.verify:
        problems = store.verify()
        for problem in problems:
            print(f'  ERROR {problem}')
        print(f'{len(entries) - len(problems)} of {len(entries)} file(s) verified')
        return 1 if problems else 0
    for entry in entries:
        meta = entry.meta
        species = ', '.join(meta.get('species') or [])
        print(f'  {meta.get("provider", "?"):9s} {meta.get("kind", "?"):15s} {meta.get("retrieved") or "undated":10s} {species:12s} {entry.relative}')
    return 0
