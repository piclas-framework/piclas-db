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
"""Layout-independent data model of a PICLas database

All readers (current species database, legacy XSec and legacy electronic state databases) fill these classes, all later commands
(check, diff, migrate, build, export) work on them. Names and keys follow the PICLas layout described in docs/layout.md.
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
from dataclasses import dataclass, field
from enum import Enum, unique
from typing import Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import numpy as np
import numpy.typing as npt

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.schema import Schema
# ==================================================================================================================================

# Attribute values after decoding: Python scalars, strings, lists of strings or numeric arrays
AttrValue = object
FloatArray = npt.NDArray[np.float64]


@unique
class XSecKind(Enum):
    """Kind of a cross-section, given by its dataset name (top level of a pair) or its group name"""

    EFFECTIVE = 'EFFECTIVE'
    ELASTIC = 'ELASTIC'
    BACKSCATTER = 'BACKSCATTER'
    ROTATION = 'ROTATION'
    VIBRATION = 'VIBRATION'
    ELECTRONIC = 'ELECTRONIC'
    REACTION = 'REACTION'
    SPECTRUM = 'SPECTRUM'
    UNDEFINED = 'UNDEFINED'  # written by create_xsec_db_lxcat.py for excitations it could not assign
    UNKNOWN = 'UNKNOWN'  # any other name, e.g. a typo such as ELECTRONIIC (ignored by PICLas)


# Kinds stored as a single dataset directly in the collision pair group, and kinds stored as datasets in a sub-group
XSEC_DATASET_KINDS = (XSecKind.EFFECTIVE, XSecKind.ELASTIC, XSecKind.BACKSCATTER)
XSEC_GROUP_KINDS = (XSecKind.ROTATION, XSecKind.VIBRATION, XSecKind.ELECTRONIC, XSecKind.REACTION, XSecKind.SPECTRUM, XSecKind.UNDEFINED)
# Kinds whose dataset name is the threshold energy in eV (parsed by PICLas)
XSEC_THRESHOLD_KINDS = (XSecKind.ROTATION, XSecKind.VIBRATION, XSecKind.ELECTRONIC, XSecKind.UNDEFINED)


@dataclass
class Provenance:
    """Origin of a piece of data, collected from the different attribute variants found in old files"""

    reference: Optional[str] = None  # 'Reference', '* Reference' or 'Source'
    info: Optional[str] = None  # LXCat 'Info' (process description, parameters, comments)
    extra: dict[str, AttrValue] = field(default_factory=dict)  # any other metadata attribute (e.g. 'Note', 'PROCESS', '* Created')
    reference_parts: list[tuple[str, str]] = field(default_factory=list)  # (label, text) rows of a tabular reference, e.g. ('MassIC', 'ATcT ...')

    @property
    def is_empty(self) -> bool:
        return self.reference is None and self.info is None and not self.extra


@dataclass
class Species:
    """Species with its physical properties (attributes read by PICLas) and level data"""

    name: str
    attributes: dict[str, AttrValue] = field(default_factory=dict)  # PICLas attributes, e.g. MassIC, omega
    electronic_levels: Optional[FloatArray] = None  # (n_rows, 2): degeneracy, energy [K]
    electronic_placeholder: bool = False  # True if the file holds a placeholder (e.g. [0]) instead of levels
    vibrational_levels: Optional[FloatArray] = None  # (n_rows, 1): energy [K]
    provenance: Provenance = field(default_factory=Provenance)
    dtypes: dict[str, str] = field(default_factory=dict)  # on-disk dtype of each dataset (e.g. ElectronicLevel: float32)


@dataclass
class Reaction:
    """Reaction of the chemistry models, all information is stored in attributes"""

    name: str  # e.g. 'CO2+M_CO+M+O#1'
    attributes: dict[str, AttrValue] = field(default_factory=dict)
    provenance: Provenance = field(default_factory=Provenance)

    @property
    def reactants(self) -> list[str]:
        return _as_list(self.attributes.get('Reactants'))

    @property
    def products(self) -> list[str]:
        return _as_list(self.attributes.get('Products'))


@dataclass
class CrossSection:
    """Single cross-section dataset of a collision pair"""

    kind: XSecKind
    key: str  # dataset name: kind name for top-level datasets, threshold or products for datasets in a sub-group
    data: FloatArray  # (n_rows, 2): energy [eV], cross-section [m^2]
    group: Optional[str] = None  # sub-group name as found in the file (keeps typos such as 'ELECTRONIIC')
    threshold: Optional[float] = None  # [eV] from the dataset name or the 'Threshold [eV]' attribute
    dtype: str = 'float64'  # dtype on disk
    provenance: Provenance = field(default_factory=Provenance)


@dataclass
class CollisionPair:
    """All cross-sections of one collision pair, e.g. 'Ar-electron'"""

    name: str
    cross_sections: list[CrossSection] = field(default_factory=list)
    empty_groups: list[str] = field(default_factory=list)
    provenance: Provenance = field(default_factory=Provenance)

    def of_kind(self, kind: XSecKind) -> list[CrossSection]:
        return [xsec for xsec in self.cross_sections if xsec.kind is kind]


@dataclass
class DiffusionSet:
    """Drift-diffusion transport data of one background gas mixture and source database"""

    pair: str  # e.g. 'Ar-electron'
    database: str  # e.g. 'Biagi-v7.1'
    datasets: dict[str, FloatArray] = field(default_factory=dict)  # DIFFUSION, MOBILITY, IONIZATION, ENERGY
    provenance: Provenance = field(default_factory=Provenance)


@dataclass
class SurfaceEntry:
    """Surface chemistry entry: sticking coefficient table or catalytic reaction"""

    name: str
    data: Optional[npt.NDArray] = None
    attributes: dict[str, AttrValue] = field(default_factory=dict)
    provenance: Provenance = field(default_factory=Provenance)


@dataclass
class Database:
    """Complete content of a database file, independent of its layout"""

    path: str
    schema: Schema
    species: dict[str, Species] = field(default_factory=dict)
    reactions: dict[str, Reaction] = field(default_factory=dict)
    collision_pairs: dict[str, CollisionPair] = field(default_factory=dict)
    diffusion: list[DiffusionSet] = field(default_factory=list)
    surface: dict[str, SurfaceEntry] = field(default_factory=dict)
    attributes: dict[str, AttrValue] = field(default_factory=dict)  # attributes of the file root or of the top-level groups
    unreadable: list[str] = field(default_factory=list)  # paths of datasets that could not be read

    def summary(self) -> dict[str, int]:
        """Number of entries per category"""
        return {
            'species': len(self.species),
            'electronic level sets': sum(spec.electronic_levels is not None for spec in self.species.values()),
            'reactions': len(self.reactions),
            'collision pairs': len(self.collision_pairs),
            'cross-sections': sum(len(pair.cross_sections) for pair in self.collision_pairs.values()),
            'diffusion sets': len(self.diffusion),
            'surface entries': len(self.surface),
        }


def _as_list(value: AttrValue) -> list[str]:
    """Attribute value as list of strings (string arrays, single strings or missing attributes)"""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return [str(value)]
