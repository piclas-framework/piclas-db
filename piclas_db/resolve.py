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
"""Lookup of the original files a database needs: local store, then private repository, then automatic or guided download"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import datetime
import os
import shutil
from dataclasses import dataclass
from enum import Enum, unique
from typing import Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db import git
from piclas_db.store import META_SUFFIX, Store, StoreEntry
# ==================================================================================================================================


@unique
class Origin(Enum):
    LOCAL = 'local store'
    PRIVATE = 'private repository'
    AUTOMATIC = 'automatic download'
    MANUAL = 'manual download'


@dataclass(frozen=True)
class Requirement:
    """Original file needed for a build: provider and dataset, optionally a specific version (sha256 prefix)"""

    provider: str
    dataset: str
    sha256: Optional[str] = None

    @classmethod
    def parse(cls, text: str) -> 'Requirement':
        """'lxcat/biagi-v7.1+phelps/ar' or 'lxcat/biagi-v7.1+phelps/ar@95a5d06a'"""
        name, _, checksum = text.partition('@')
        provider, _, dataset = name.strip('/').partition('/')
        if not provider or not dataset:
            raise ValueError(f'expected <provider>/<dataset>[@sha256], got {text!r}')
        return cls(provider=provider, dataset=dataset, sha256=checksum or None)

    def __str__(self) -> str:
        return f'{self.provider}/{self.dataset}' + (f'@{self.sha256}' if self.sha256 else '')

    def matches(self, entry: StoreEntry) -> bool:
        meta = entry.meta
        if meta.get('provider') != self.provider or meta.get('dataset') != self.dataset:
            return False
        return self.sha256 is None or str(meta.get('sha256', '')).startswith(self.sha256)


@dataclass
class Resolution:
    requirement: Requirement
    origin: Origin
    entry: Optional[StoreEntry] = None


def mirror_url(argument: Optional[str], store: Store) -> Optional[str]:
    """Private repository: command line, then $PICLAS_DB_MIRROR, then the remote of an existing clone"""
    return argument or os.environ.get('PICLAS_DB_MIRROR') or (git.remote_url(store.root) if store.is_repository else None)


def find(store: Store, requirement: Requirement) -> Optional[StoreEntry]:
    """Newest matching file (by retrieval date)"""
    matches = [entry for entry in store.entries() if requirement.matches(entry)]
    return max(matches, key=lambda entry: str(entry.meta.get('retrieved') or ''), default=None)


def resolve(store: Store, requirements: list[Requirement], update: bool = True) -> list[Resolution]:
    """Locate every requirement; updates the store from the private repository once if something is missing locally"""
    resolutions = [Resolution(requirement, Origin.LOCAL, find(store, requirement)) for requirement in requirements]
    missing = [resolution for resolution in resolutions if resolution.entry is None]
    if missing and update and store.is_repository:
        git.pull(store.root)
        store.write_index()
        for resolution in missing:
            resolution.entry, resolution.origin = find(store, resolution.requirement), Origin.PRIVATE
    for resolution in resolutions:
        if resolution.entry is None:
            # No provider supports automatic downloads yet (candidate: IAEA CollisionDB API); everything is downloaded by hand
            resolution.origin = Origin.MANUAL
    return resolutions


def synchronize(store: Store, url: Optional[str]) -> str:
    """Make the store a current clone of the private repository; returns a description of what was done"""
    root = store.root
    if store.is_repository:
        current = git.remote_url(root)
        if url and current and url != current:
            raise git.GitError(f'the store is a clone of {current}, not of {url}')
        git.pull(root)
        store.write_index()
        return f'updated from {current}'
    if not url:
        raise git.GitError('no private repository given (use --mirror or $PICLAS_DB_MIRROR)')
    if not root.exists() or not any(root.iterdir()):
        root.parent.mkdir(parents=True, exist_ok=True)
        if root.exists():
            root.rmdir()
        git.clone(url, root)
        store.write_index()
        return f'cloned from {url}'

    # Existing local store: clone next to it, add the local files that are not in the repository, then swap the directories
    clone = root.with_name(f'.{root.name}.clone')
    if clone.exists():
        shutil.rmtree(clone)
    git.clone(url, clone)
    added = []
    for meta_file in sorted(root.rglob(f'*{META_SUFFIX}')):
        relative = meta_file.relative_to(root)
        original = meta_file.with_name(meta_file.name[: -len(META_SUFFIX)])
        if (clone / relative).exists() or not original.is_file():
            continue
        for source in (original, meta_file):
            target = clone / source.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            added.append(target)
    if added:
        git.exclude(clone, 'index.yaml')
        git.commit(clone, added, f'Add {len(added) // 2} file(s) from an existing local store')
    backup = root.with_name(f'{root.name}.backup-{datetime.datetime.now():%Y%m%d-%H%M%S}')
    root.rename(backup)
    clone.rename(root)
    store.write_index()
    return f'cloned from {url}, {len(added) // 2} local file(s) added (old store kept as {backup})'


def store_status(store: Store) -> str:
    if not store.is_repository:
        return 'not connected to a private repository'
    count = git.unpushed(store.root)
    return f'{count} local commit(s) not pushed (piclas-db push)' if count else 'in sync with the private repository'
