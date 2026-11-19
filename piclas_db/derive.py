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
"""Species attributes derived from others in the database, so that they are consistent by construction (recipe options):

    masses: composition   MassIC of every molecule and ion = sum of the masses of its atoms (the neutral atom species of the
                          database, e.g. from ATcT) minus charge x electron mass (species 'electron', else CODATA): every reaction
                          conserves mass exactly. ATcT gives masses to about four decimals in u, which loses the electron mass
                          (SpeciesDatabase.h5: XeIon1 is Xe minus 0.911 electron masses)
    charges: name         ChargeIC = charge from the name (ArIon1: 1, electron: -1) x elementary charge (SI, exact)

Values written in the recipe take precedence.
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import re

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.atct_map import piclas_name
from piclas_db.model import Database, Species
# ==================================================================================================================================

ELECTRON_MASS = 9.1093837139e-31  # kg, CODATA 2022
ELEMENTARY_CHARGE = 1.602176634e-19  # C, exact (SI 2019)
MASSES = ('record', 'composition')
CHARGES = ('data', 'name')


def add_reference(species: Species, text: str) -> None:
    species.provenance.reference = '; '.join(filter(None, [species.provenance.reference, text]))


def composition_text(counts: dict[str, int], charge: int) -> str:
    text = ' + '.join(f'{count} {element}' if count > 1 else element for element, count in counts.items())
    return text + (f' - {charge} e' if charge > 1 else ' - e' if charge == 1 else '')


def derive_masses(database: Database, fixed: dict[str, dict[str, object]], notes: list[str]) -> None:
    """MassIC by composition for every species that is not a neutral atom or the electron (see module docstring)"""
    parsed = {name: piclas_name(name) for name in database.species if name != 'electron'}
    atoms: dict[str, float] = {}
    for name, value in parsed.items():
        mass = database.species[name].attributes.get('MassIC')
        if value is not None and value[2] == 0 and sum(value[1].values()) == 1 and isinstance(mass, (int, float)):
            atoms[next(iter(value[1]))] = float(mass)
    electron = database.species.get('electron')
    electron_mass = electron.attributes.get('MassIC') if electron is not None else None
    if not isinstance(electron_mass, (int, float)):
        electron_mass = ELECTRON_MASS
        notes.append(f'masses: composition: no electron mass in the database, CODATA 2022 used ({ELECTRON_MASS} kg)')
    changed: list[tuple[float, str]] = []
    for name, value in parsed.items():
        species = database.species[name]
        if value is None or (value[2] == 0 and sum(value[1].values()) == 1) or 'MassIC' in (fixed.get(name) or {}):
            continue
        _, counts, charge = value
        missing = sorted(element for element in counts if element not in atoms)
        if missing:
            notes.append(f'{name}: MassIC not by composition, no mass of the atom(s) {", ".join(missing)} in the database')
            continue
        mass = sum(count * atoms[element] for element, count in counts.items()) - charge * float(electron_mass)
        old = species.attributes.get('MassIC')
        if isinstance(old, (int, float)) and old:
            changed.append((abs(mass - old) / abs(old), name))
        species.attributes['MassIC'] = mass
        # the ATcT reference names only what is taken from the record
        species.provenance.reference = re.sub(r'(ATcT [^;]*\)): HeatOfFormation_K, MassIC', r'\1: HeatOfFormation_K', species.provenance.reference or '') or None
        species.provenance.reference = re.sub(r'(; )?ATcT [^;]*\): MassIC(?=;|$)', '', species.provenance.reference or '') or None
        add_reference(species, f'MassIC: by composition, {composition_text(counts, charge)} (masses of the atom species and the electron)')
    if changed:
        largest = max(changed)
        notes.append(f'masses: composition: MassIC of {len(changed)} species from their atoms (largest change {largest[0]:.1e}, {largest[1]})')


def derive_charges(database: Database, fixed: dict[str, dict[str, object]], notes: list[str]) -> None:
    """ChargeIC from the name x elementary charge for every species with a name of the form <formula>[Ion<n>] and the electron"""
    changed = []
    for name, species in database.species.items():
        if 'ChargeIC' in (fixed.get(name) or {}):
            continue
        parsed = piclas_name(name) if name != 'electron' else ('e', {}, -1)
        if parsed is None:
            notes.append(f'{name}: ChargeIC not from the name (name not understood)')
            continue
        charge = parsed[2] * ELEMENTARY_CHARGE
        if species.attributes.get('ChargeIC') != charge:
            changed.append(name)
        species.attributes['ChargeIC'] = charge
    if changed:
        notes.append(f'charges: name: ChargeIC of {len(changed)} species set to charge x {ELEMENTARY_CHARGE} C')
