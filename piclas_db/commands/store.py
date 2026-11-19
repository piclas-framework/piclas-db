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
import pathlib

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db import git
from piclas_db.store import META_SUFFIX, Store
# ==================================================================================================================================


def commit_pending(store: Store) -> int:
    """Commit store files that are not committed yet (e.g. an import whose commit failed); only verified files and their meta"""
    if not store.is_repository:
        print('ERROR: the store is not a clone of a private repository')
        return 1
    changed = {line.split(maxsplit=1)[1].strip('"') for line in git.changes(store.root)}  # 'XY path' (the first line may lose its blank)
    if not changed:
        print('Nothing to commit: the clone has no uncommitted changes')
        return 0
    files: list[pathlib.Path] = []
    problems = {problem.split(':', 1)[0] for problem in store.verify()}  # changed or missing originals are never committed
    for entry in store.entries():
        meta = entry.path.with_name(entry.path.name + META_SUFFIX)
        pending = [path for path in (entry.path, meta) if str(path.relative_to(store.root)) in changed or any(str(path.relative_to(store.root)).startswith(item.rstrip('/') + '/') for item in changed)]
        if pending and entry.relative not in problems:
            files.extend(pending)
    if not files:
        print('No store files among the uncommitted changes; they are not from piclas-db (git -C <store> status):')
        for item in sorted(changed)[:10]:
            print(f'    {item}')
        return 1
    git.commit(store.root, files, f'Add {len(files)} file(s) of the store that were not committed')
    print(f'Committed {len(files)} file(s); push with piclas-db push')
    rest = git.changes(store.root)
    if rest:
        print(f'Still uncommitted (not store files): {len(rest)}; see git -C {store.root} status')
    return 0


def run(args: argparse.Namespace) -> int:
    """List the local store, or verify that every file still matches its sha256"""
    store = Store(args.store)
    entries = store.entries()
    if store.is_repository and entries:
        store.write_index()  # also stops tracking an index.yaml that was committed by hand
    print(f'Store: {store.root} ({len(entries)} file(s))')
    if args.commit:
        return commit_pending(store)
    if store.is_repository:
        changed = git.changes(store.root)
        if changed:
            # e.g. a file copied into the store whose commit failed, or a file changed by hand: git pull refuses to work then
            print(f'  {len(changed)} uncommitted change(s) in the clone of the private repository:')
            for line in changed[:10]:
                print(f'    {line}')
            print('  Files that belong in the store: piclas-db store --commit; anything else: remove it (git -C <store> status)')
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
