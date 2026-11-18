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
"""Reading of any source into the data model: database files, ASCII tables and original downloads (LXCat, NIST ASD)"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import pathlib
import zipfile
from typing import Optional, Union

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.build import BuildError, lxcat_database, nist_database
from piclas_db.model import Database
from piclas_db.readers import DatabaseReadError, read_database
from piclas_db.sources.identify import read_text
from piclas_db.sources.lxcat import is_lxcat, is_lxcat_xml, load_lxcat
from piclas_db.sources.nist import is_nist_levels
# ==================================================================================================================================


def read_any(path: Union[str, pathlib.Path], species: Optional[str] = None) -> Database:
    """Database file (.h5, any layout), directory with ASCII tables, or original LXCat / NIST ASD download"""
    path = pathlib.Path(path)
    if path.is_dir() or (path.is_file() and path.read_bytes()[:8] == b'\x89HDF\r\n\x1a\n'):
        return read_database(path)
    if not path.is_file():
        raise DatabaseReadError(f'file not found: {path}')
    try:
        if zipfile.is_zipfile(path):
            return lxcat_database(load_lxcat(path), str(path))
        text = read_text(path)
        if text is not None and (is_lxcat(text) or is_lxcat_xml(text)):
            return lxcat_database(load_lxcat(path), str(path))
        if text is not None and is_nist_levels(text):
            return nist_database(text, str(path), species)
    except (ValueError, BuildError) as e:
        raise DatabaseReadError(f'{path}: {e}') from e
    raise DatabaseReadError(f'{path}: not a database, table directory, LXCat or NIST ASD file')
