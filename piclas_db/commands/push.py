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
from piclas_db import git
from piclas_db.common.progress import progress
from piclas_db.store import Store
# ==================================================================================================================================


def run(args: argparse.Namespace) -> int:
    """Commit remaining changes of the local store and push it to the private repository"""
    store = Store(args.store)
    if not store.is_repository:
        print(f'ERROR: {store.root} is not connected to a private repository (piclas-db fetch --mirror <ssh url>)')
        return 1
    problems = store.verify()
    if problems:
        for problem in problems:
            print(f'ERROR {problem}')
        print('Not pushed: the store contains changed or missing files')
        return 1
    try:
        if git.commit(store.root, [], 'Update store'):
            print('Committed remaining changes')
        count = git.unpushed(store.root)
        if count == 0:
            print('Nothing to push, the store is in sync with the private repository')
            return 0
        with progress('pushing to the private repository'):
            git.push(store.root)
    except git.GitError as e:
        print(f'ERROR: {e}')
        return 1
    print(f'Pushed {count} commit(s) to {git.remote_url(store.root)}')
    return 0
