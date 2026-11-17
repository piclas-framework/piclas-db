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
"""Reference values used by the checks

Ionization energies and ground-state degeneracies g = 2J+1 of atoms and atomic ions, from the NIST Atomic Spectra Database
(https://physics.nist.gov/asd). Only well-established values are listed; species without an entry are not checked against them.
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
from typing import Final
# ==================================================================================================================================

# Conversion factors
EV_TO_K: Final[float] = 11604.51812  # 1 eV / k_B in K
CM_TO_K: Final[float] = 1.438776877  # h c / k_B in cm K (second radiation constant)

# Energies above this value are dummy levels (e.g. 1e32 K) used for species with only a ground state
DUMMY_LEVEL_K: Final[float] = 1.0e10

# Ionization energy [eV] of the species (energy to remove the next electron)
IONIZATION_ENERGY_EV: Final[dict[str, float]] = {
    'H': 13.598434,
    'He': 24.587389,
    'HeIon1': 54.417765,
    'C': 11.260288,
    'CIon1': 24.383154,
    'CIon2': 47.88778,
    'CIon3': 64.49352,
    'CIon4': 392.0905,
    'CIon5': 489.99320,
    'N': 14.53413,
    'NIon1': 29.60125,
    'O': 13.618054,
    'OIon1': 35.12112,
    'Ar': 15.759610,
    'ArIon1': 27.62966,
    'ArIon2': 40.735,
    'Xe': 12.129843,
    'XeIon1': 20.975,
    'Fe': 7.902468,
    'FeIon1': 16.1992,
}

# Degeneracy g = 2J+1 of the ground state (J-resolved, as given by NIST ASD)
GROUND_STATE_DEGENERACY: Final[dict[str, int]] = {
    'H': 2,  # 2S1/2
    'He': 1,  # 1S0
    'HeIon1': 2,  # 2S1/2
    'C': 1,  # 3P0
    'CIon1': 2,  # 2P1/2
    'CIon2': 1,  # 1S0
    'CIon3': 2,  # 2S1/2
    'CIon4': 1,  # 1S0
    'CIon5': 2,  # 2S1/2
    'N': 4,  # 4S3/2
    'NIon1': 1,  # 3P0
    'O': 5,  # 3P2
    'OIon1': 4,  # 4S3/2
    'Ar': 1,  # 1S0
    'ArIon1': 4,  # 2P3/2
    'ArIon2': 5,  # 3P2
    'Xe': 1,  # 1S0
    'XeIon1': 4,  # 2P3/2
    'Fe': 9,  # 5D4
    'FeIon1': 10,  # 6D9/2
}

# Attributes of /Species/<name> read by PICLas (docs/layout.md)
SPECIES_ATTRIBUTES: Final[tuple[str, ...]] = (
    'MassIC',
    'ChargeIC',
    'InteractionID',
    'Tref',
    'dref',
    'omega',
    'alphaVSS',
    'FullyIonized',
    'HeatOfFormation_K',
    'PreviousState',
    'SymmetryFactor',
    'PolyatomicMol',
    'LinearMolec',
    'NumOfAtoms',
    'CharaTempVib',
    'CharaTempRot',
    'MomentOfInertia',
    'Ediss_eV',
    'Vib-OmegaE',
    'Vib-ChiE',
)
SPECIES_REQUIRED_ATTRIBUTES: Final[tuple[str, ...]] = ('MassIC', 'InteractionID')

# Fully ionized species (no electrons left): no electronic levels expected
FULLY_IONIZED: Final[tuple[str, ...]] = ('HIon1', 'HeIon2', 'CIon6', 'NIon7', 'OIon8')
