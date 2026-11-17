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
"""Provenance of database files written by piclas-db

Every file written by build, migrate or rebuild carries root attributes that say exactly how it was made, so that it can be traced
and rebuilt with the same or a newer version of piclas-db. PICLas does not read root attributes.

    * piclas-db format          'PICLas species database'
    * piclas-db format version  version of the layout (docs/layout.md), increased with incompatible changes
    * piclas-db version         version of piclas-db, e.g. '0.12.0'
    * piclas-db commit          git commit of piclas-db, if run from a git checkout
    * piclas-db created         UTC time of creation (ISO 8601)
    * piclas-db command         command that wrote the file, e.g. 'build recipes/gec-argon.yaml'
    * piclas-db recipe          recipe as YAML text (build, rebuild; contains no third-party data)
    * piclas-db recipe sha256   sha256 of the recipe text
    * piclas-db sources         one line per original file: '<provider>/<dataset> | <file in the store> | sha256 <...> | retrieved <date>'
    * piclas-db input           input file of migrate or rebuild: '<path> | sha256 <...> | <layout>'
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import datetime
import hashlib
import pathlib
import re
from dataclasses import dataclass, field
from typing import Final, Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.common.common_vars import Common
# ==================================================================================================================================

PROVENANCE_PREFIX: Final[str] = '* piclas-db '
FORMAT: Final[str] = 'PICLas species database'
FORMAT_VERSION: Final[int] = 1  # layout of docs/layout.md


def key(name: str) -> str:
    return PROVENANCE_PREFIX + name


def file_sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as file:
        for chunk in iter(lambda: file.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def create(
    command: str,
    recipe_text: Optional[str] = None,
    sources: Optional[list[tuple[str, str, str, Optional[str]]]] = None,
    input_file: Optional[tuple[pathlib.Path, str]] = None,
) -> dict[str, object]:
    """Provenance attributes for a new file

    sources: (requirement, file in the store, sha256, retrieval date) per original file; input_file: (path, layout name)
    """
    common = Common()
    attributes: dict[str, object] = {
        key('format'): FORMAT,
        key('format version'): FORMAT_VERSION,
        key('version'): common.version,
        key('commit'): common.commit or 'unknown',
        key('created'): datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat(),
        key('command'): command,
    }
    if recipe_text is not None:
        attributes[key('recipe')] = recipe_text
        attributes[key('recipe sha256')] = hashlib.sha256(recipe_text.encode('utf-8')).hexdigest()
    if sources:
        attributes[key('sources')] = [f'{requirement} | {file} | sha256 {checksum} | retrieved {retrieved or "unknown"}' for requirement, file, checksum, retrieved in sources]
    if input_file is not None:
        path, layout = input_file
        attributes[key('input')] = f'{path} | sha256 {file_sha256(path) if path.is_file() else "directory"} | {layout}'
    return attributes


@dataclass
class FileProvenance:
    """Provenance read from a database file"""

    format_version: Optional[int] = None
    version: Optional[str] = None
    commit: Optional[str] = None
    created: Optional[str] = None
    command: Optional[str] = None
    recipe: Optional[str] = None
    recipe_sha256: Optional[str] = None
    sources: list[str] = field(default_factory=list)
    input: Optional[str] = None

    @property
    def present(self) -> bool:
        return self.version is not None

    @property
    def recipe_intact(self) -> bool:
        """The stored recipe matches its sha256"""
        if self.recipe is None or self.recipe_sha256 is None:
            return False
        return hashlib.sha256(self.recipe.encode('utf-8')).hexdigest() == self.recipe_sha256

    def source_checksums(self) -> list[str]:
        return [match.group(1) for line in self.sources if (match := re.search(r'sha256 ([0-9a-f]{64})', line))]


def read(attributes: dict[str, object]) -> FileProvenance:
    def text(name: str) -> Optional[str]:
        value = attributes.get(key(name))
        return None if value is None else str(value)

    version = attributes.get(key('format version'))
    sources = attributes.get(key('sources'))
    return FileProvenance(
        format_version=int(version) if isinstance(version, (int, float)) else None,
        version=text('version'),
        commit=text('commit'),
        created=text('created'),
        command=text('command'),
        recipe=text('recipe'),
        recipe_sha256=text('recipe sha256'),
        sources=[str(line) for line in sources] if isinstance(sources, list) else ([str(sources)] if sources else []),
        input=text('input'),
    )
