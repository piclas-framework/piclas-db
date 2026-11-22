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
"""Papers wanted but not yet in the store: literature/wanted.yaml in the private store

Each entry names the paper (key, citation, DOI if known), what it is needed for, and notes such as failed download attempts. `piclas-db
store` reports how many papers are wanted; importing a paper whose key or DOI matches an entry removes it. The file lives in the private
store because it shows which papers the store holds and which it lacks.
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import datetime
from typing import Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import yaml

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db import git
from piclas_db.sources.identify import slug
from piclas_db.store import Store
# ==================================================================================================================================

FILE = 'literature/wanted.yaml'
HEADER = '# Papers wanted for the store (piclas-db literature want / wanted); entries are removed when the paper is imported\n'


class WantedError(Exception):
    pass


def load(store: Store) -> dict[str, dict]:
    path = store.root / FILE
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    if not isinstance(data, dict):
        raise WantedError(f'{path}: expected a mapping of paper keys to entries')
    return {str(key): dict(value or {}) for key, value in data.items()}


def save(store: Store, wanted: dict[str, dict], message: str) -> None:
    """Write the list (removed when empty) and commit it in a store that is a git repository"""
    path = store.root / FILE
    if wanted:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(HEADER + yaml.safe_dump(wanted, sort_keys=True, allow_unicode=True, width=1000), encoding='utf-8')
    elif path.exists():
        path.unlink()
    else:
        return
    if store.is_repository:
        git.commit(store.root, [path], message)


def add(store: Store, key: str, reference: str, needed_for: Optional[str] = None, doi: Optional[str] = None, note: Optional[str] = None, by: Optional[str] = None) -> str:
    """Add or update an entry; returns the key (slugged)"""
    name = slug(key)
    wanted = load(store)
    entry = wanted.get(name, {})
    entry.update({'reference': reference, 'added': entry.get('added') or datetime.date.today().isoformat()})
    for field, value in (('needed_for', needed_for), ('doi', doi), ('by', by)):
        if value:
            entry[field] = value
    if note:
        entry['notes'] = [*entry.get('notes', []), note]
    wanted[name] = entry
    save(store, wanted, f'Wanted: {name}')
    return name


def drop(store: Store, key: str) -> None:
    wanted = load(store)
    if slug(key) not in wanted:
        raise WantedError(f'{key} is not on the wanted list (piclas-db literature wanted)')
    del wanted[slug(key)]
    save(store, wanted, f'No longer wanted: {slug(key)}')


def fulfilled(store: Store, key: Optional[str], doi: Optional[str]) -> list[str]:
    """Remove the entries matching an imported paper (same key or DOI, case-insensitive); returns their keys"""
    wanted = load(store)
    matches = [name for name, entry in wanted.items() if (key and name == slug(key)) or (doi and str(entry.get('doi') or '').lower() == doi.lower())]
    if matches:
        for name in matches:
            del wanted[name]
        save(store, wanted, 'No longer wanted: ' + ', '.join(matches))
    return matches


def describe(wanted: dict[str, dict]) -> list[str]:
    lines = []
    for name, entry in sorted(wanted.items()):
        lines.append(f'{name:24s} {entry.get("reference", "")}')
        if entry.get('doi'):
            lines.append(f'{"":24s} https://doi.org/{entry["doi"]}')
        if entry.get('needed_for'):
            lines.append(f'{"":24s} needed for: {entry["needed_for"]}')
        lines.extend(f'{"":24s} note: {note}' for note in entry.get('notes', []))
    return lines
