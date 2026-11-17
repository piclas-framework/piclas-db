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
from enum import Enum, unique

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import h5py
# ==================================================================================================================================

# Top-level groups of the current PICLas species database layout (SpeciesDatabase.h5)
SPECIES_DATABASE_GROUPS = ('Species', 'Reactions', 'Cross-Sections', 'Diffusion-Coefficients', 'Surface-Chemistry')


@unique
class Schema(Enum):
    """Known layouts of PICLas database files"""

    SPECIES_DATABASE = 'species database (SpeciesDatabase.h5 layout)'
    LEGACY_XSEC = 'legacy cross-section database (XSec_Database_*.h5)'
    LEGACY_ELECTRONIC = 'legacy electronic state database (DSMCSpecies_electronic_state_*.h5)'
    ASCII_TABLES = 'ASCII tables (piclas-db export)'
    UNKNOWN = 'unknown layout'


def detect_schema(h5: h5py.File) -> Schema:
    """Determine the layout of an opened HDF5 file from its top-level structure"""
    keys = list(h5.keys())
    if not keys:
        return Schema.UNKNOWN

    # Current layout: fixed set of top-level groups
    if any(key in SPECIES_DATABASE_GROUPS for key in keys):
        return Schema.SPECIES_DATABASE

    # Legacy electronic state database: one (n_rows, 2) dataset per species directly in the root
    if all(isinstance(h5[key], h5py.Dataset) and h5[key].ndim == 2 and h5[key].shape[1] == 2 for key in keys):
        return Schema.LEGACY_ELECTRONIC

    # Legacy cross-section database: collision-pair groups (e.g. Ar-electron) directly in the root
    if all(isinstance(h5[key], h5py.Group) and '-' in key for key in keys):
        return Schema.LEGACY_XSEC

    return Schema.UNKNOWN
