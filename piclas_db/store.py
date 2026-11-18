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
"""Local store of original data files

The store keeps every imported file byte for byte, sorted by provider and dataset, next to a meta.yaml with its provenance:

    <store>/index.yaml                                    generated list of all files
    <store>/<provider>/<dataset>/<retrieved>_<sha8>.<ext>  original file, never modified or overwritten
    <store>/<provider>/<dataset>/<retrieved>_<sha8>.meta.yaml

The default location is $PICLAS_DB_STORE, otherwise $XDG_DATA_HOME/piclas-db/store (~/.local/share/piclas-db/store). The store
can be a clone of the private source repository ('piclas-db fetch --mirror URL'); then every import is committed and
'piclas-db push' backs it up. index.yaml is generated locally and excluded from git (.git/info/exclude), so that imports on
different machines never conflict. The store is never published.
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import datetime
import hashlib
import os
import pathlib
import shutil
from dataclasses import dataclass
from typing import Optional, Union

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import yaml

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db import git
from piclas_db.common.common_vars import Common
from piclas_db.sources.identify import Identified
# ==================================================================================================================================

META_SUFFIX = '.meta.yaml'


def default_store() -> pathlib.Path:
    """$PICLAS_DB_STORE, then 'store' in the configuration file, then $XDG_DATA_HOME/piclas-db/store"""
    from piclas_db import config  # noqa: PLC0415

    if os.environ.get('PICLAS_DB_STORE'):
        return pathlib.Path(os.environ['PICLAS_DB_STORE']).expanduser()
    if config.value('store'):
        return pathlib.Path(str(config.value('store'))).expanduser()
    data_home = os.environ.get('XDG_DATA_HOME') or str(pathlib.Path.home() / '.local' / 'share')
    return pathlib.Path(data_home) / 'piclas-db' / 'store'


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as file:
        for chunk in iter(lambda: file.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class StoreEntry:
    path: pathlib.Path  # original file in the store
    meta: dict

    @property
    def relative(self) -> str:
        return str(self.meta.get('file', self.path.name))


class Store:
    def __init__(self, root: Optional[Union[str, pathlib.Path]] = None) -> None:
        self.root = pathlib.Path(root).expanduser() if root else default_store()

    def entries(self) -> list[StoreEntry]:
        if not self.root.is_dir():
            return []
        entries = []
        for meta_file in sorted(self.root.rglob(f'*{META_SUFFIX}')):
            if '.git' in meta_file.relative_to(self.root).parts:
                continue
            with meta_file.open(encoding='utf-8') as file:
                meta = yaml.safe_load(file) or {}
            entries.append(StoreEntry(path=meta_file.with_name(meta_file.name[: -len(META_SUFFIX)]), meta=meta))
        return entries

    @property
    def is_repository(self) -> bool:
        return git.is_repository(self.root)

    def find(self, checksum: str) -> Optional[StoreEntry]:
        return next((entry for entry in self.entries() if entry.meta.get('sha256') == checksum), None)

    def target(self, identified: Identified, checksum: str, suffix: str, retrieved: Optional[datetime.date]) -> pathlib.Path:
        stamp = retrieved.isoformat() if retrieved else 'undated'
        return self.root / identified.provider / identified.dataset / f'{stamp}_{checksum[:8]}{suffix}'

    def add(self, source: pathlib.Path, identified: Identified, retrieved: Optional[datetime.date] = None, by: Optional[str] = None) -> StoreEntry:
        """Copy a file into the store and write its meta.yaml; the caller checks for duplicates first"""
        checksum = sha256(source)
        retrieved = retrieved or identified.retrieved
        target = self.target(identified, checksum, source.suffix or '.txt', retrieved)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        meta = {
            'file': str(target.relative_to(self.root)),
            'provider': identified.provider,
            'kind': identified.kind,
            'dataset': identified.dataset,
            'species': identified.species,
            'retrieved': retrieved.isoformat() if retrieved else None,
            'retrieved_source': 'file content' if identified.retrieved and retrieved == identified.retrieved else ('command line' if retrieved else 'unknown'),
            'original_name': source.name,
            'sha256': checksum,
            'size': source.stat().st_size,
            'imported': datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat(),
            'imported_with': Common().version_string(),
            **({'imported_by': by} if by else {}),
            **identified.details,
        }
        meta_file = target.with_name(target.name + META_SUFFIX)
        with meta_file.open('w', encoding='utf-8') as file:
            yaml.safe_dump(meta, file, sort_keys=False, allow_unicode=True, width=1000)
        self.write_index()
        if self.is_repository:
            message = f'Add {identified.provider} {identified.kind} {identified.dataset} (retrieved {meta["retrieved"] or "unknown"}, sha256 {checksum[:8]})'
            git.commit(self.root, [target, meta_file], message)
        return StoreEntry(path=target, meta=meta)

    def update_meta(self, entry: StoreEntry, message: str) -> None:
        """Rewrite the meta file of an entry (e.g. a review); the original file itself never changes"""
        meta_file = entry.path.with_name(entry.path.name + META_SUFFIX)
        with meta_file.open('w', encoding='utf-8') as file:
            yaml.safe_dump(entry.meta, file, sort_keys=False, allow_unicode=True, width=1000)
        self.write_index()
        if self.is_repository:
            git.commit(self.root, [meta_file], message)

    def write_index(self) -> None:
        index = [{key: entry.meta.get(key) for key in ('file', 'provider', 'kind', 'dataset', 'species', 'retrieved', 'sha256')} for entry in self.entries()]
        self.root.mkdir(parents=True, exist_ok=True)
        if self.is_repository:
            git.exclude(self.root, 'index.yaml')
        with (self.root / 'index.yaml').open('w', encoding='utf-8') as file:
            yaml.safe_dump({'files': index}, file, sort_keys=False, allow_unicode=True, width=1000)

    def verify(self) -> list[str]:
        """Files that are missing or whose content no longer matches the recorded sha256"""
        problems = []
        for entry in self.entries():
            if not entry.path.is_file():
                problems.append(f'{entry.relative}: file missing')
            elif sha256(entry.path) != entry.meta.get('sha256'):
                problems.append(f'{entry.relative}: content changed (sha256 mismatch)')
        return problems
