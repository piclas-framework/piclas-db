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
from collections import Counter

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.git import GitError
from piclas_db.resolve import Origin, Requirement, mirror_url, resolve, store_status, synchronize
from piclas_db.store import Store
# ==================================================================================================================================


def run(args: argparse.Namespace) -> int:
    """Clone or update the local store from the private repository; with --need, locate required original files"""
    store = Store(args.store)
    try:
        requirements = [Requirement.parse(text) for text in args.need]
    except ValueError as e:
        print(f'ERROR: {e}')
        return 1

    url = mirror_url(args.mirror, store)
    try:
        if requirements:
            if url and not store.is_repository:
                print(f'Store: {store.root}: {synchronize(store, url)}')
            resolutions = resolve(store, requirements)
        else:
            print(f'Store: {store.root}: {synchronize(store, url)}')
            resolutions = []
    except GitError as e:
        print(f'ERROR: {e}')
        if not requirements:
            print('Without access to the private repository, continue with the local store and manual downloads (piclas-db guide, piclas-db import).')
        return 1

    for resolution in resolutions:
        location = resolution.entry.relative if resolution.entry else f'download by hand (piclas-db guide {resolution.requirement}), then piclas-db import'
        print(f'  {resolution.origin.value:20s} {resolution.requirement}: {location}')
    if resolutions:
        counts = Counter(resolution.origin for resolution in resolutions)
        print(f'{len(resolutions)} needed: ' + ', '.join(f'{counts[origin]} {origin.value}' for origin in Origin if counts[origin]))
    print(f'{len(store.entries())} file(s) in the store, {store_status(store)}')
    return 1 if any(resolution.origin is Origin.MANUAL for resolution in resolutions) else 0
