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
"""Comparison of PICLas reservoir regression checks with a database ('piclas-db reservoir --regressioncheck')

The NIG_Reservoir regression checks of PICLas contain reaction rates from real PICLas runs (PartAnalyze_*_ref.csv). For every
reaction with ReactionModel = XSec and a monoenergetic projectile (velocityDistribution = constant), the rate coefficient expected
from a database (k = sigma(E) v) is compared with the reference. By default the database of the check is used; any other database
(e.g. a SpeciesDatabase.h5 built by piclas-db) can be given instead, which shows how the reference would change.
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import math
import pathlib
import re
from dataclasses import dataclass
from typing import Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import numpy as np

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.compare import canonical_pair
from piclas_db.model import Database, XSecKind
from piclas_db.plot import BOLTZMANN, EV
from piclas_db.readers import read_database
from piclas_db.reservoir import read_rates
# ==================================================================================================================================

SPEED_OF_LIGHT = 299792458.0


class RegressionCheckError(Exception):
    """Directory is not a supported reservoir regression check"""


def read_ini(*paths: pathlib.Path) -> dict[str, str]:
    """PICLas parameter files: 'key = value ! comment', keys case-insensitive; later files do not override earlier ones"""
    values: dict[str, str] = {}
    for path in paths:
        if not path.is_file():
            continue
        for raw in path.read_text(errors='replace').splitlines():
            line = raw.split('!', 1)[0].strip()
            if not line or line.startswith(';') or '=' not in line:
                continue
            name, value = (part.strip() for part in line.split('=', 1))
            values.setdefault(name.lower(), value)
    return values


def number_of(text: Optional[str], default: object) -> Optional[float]:
    """First number of a parameter value (Fortran exponents allowed), the default if there is none"""
    if text is not None:
        match = re.search(r'[-+]?\d*\.?\d+(?:[eEdD][-+]?\d+)?', text)
        if match:
            return float(match.group(0).replace('D', 'E').replace('d', 'e'))
    return float(default) if isinstance(default, (int, float)) else None


def values_of(text: str) -> list[float]:
    """Comma-separated variations of a parameter (reggie); entries that are not numbers are skipped"""
    found = [number_of(part, None) for part in text.split(',')]
    return [value for value in found if value is not None]


@dataclass
class SpeciesSetup:
    """Species as set up in the parameter files of a regression check"""

    name: str
    mass: Optional[float]
    heat: float  # heat of formation [K]
    space: str  # SpaceIC of the first initialization
    distribution: str  # velocityDistribution of the first initialization
    velocities: list[float]
    density: float
    temperature: float
    rotation: float
    molecule: bool


def indices(text: str) -> list[int]:
    return [int(part) for part in re.findall(r'-?\d+', text)]


@dataclass
class Comparison:
    case: str
    reference: str  # reference file
    reaction: int
    equation: str
    energy: float  # collision energy [eV]
    reference_rate: float
    expected: float  # sigma(E) v from the database
    deviation: Optional[float]
    probability: float  # collision probability per time step (n sigma_total v dt)
    corrected: Optional[float]  # deviation after the correction (1 - exp(-x)) / x for the collision probability


def collision_energy(velocity: float, projectile_mass: float, target_mass: float) -> float:
    """Collision energy in eV for a projectile hitting a target at rest (relativistic for fast electrons)"""
    reduced = projectile_mass * target_mass / (projectile_mass + target_mass)
    if velocity < 0.05 * SPEED_OF_LIGHT:
        return 0.5 * reduced * velocity**2 / EV
    gamma = 1.0 / math.sqrt(1.0 - (velocity / SPEED_OF_LIGHT) ** 2)
    return (gamma - 1.0) * projectile_mass * SPEED_OF_LIGHT**2 / EV


THERMAL_SAMPLES = 20000


def beam_rate(table: np.ndarray, velocity: float, projectile_mass: float, target_mass: float, temperature: float, rotational: tuple[float, ...] = ()) -> tuple[float, float]:
    """Rate coefficient <sigma(E) g> and mean collision energy for a monoenergetic projectile in a Maxwellian background

    For electrons the thermal motion of the background is negligible; for heavy projectiles it broadens the collision energy
    (e.g. H2Ion1 at 0.1 eV in H2 at 300 K). PICLas evaluates reaction cross-sections at the collision energy including the
    rotational and vibrational energy of molecular reactants (mcc_xsec.f90); rotational: temperatures of the rotational energy of
    the molecular reactants (diatomic: exponential distribution with mean k_B T). The average uses fixed samples, so results are
    reproducible.
    """
    reduced = projectile_mass * target_mass / (projectile_mass + target_mass)
    if velocity >= 0.05 * SPEED_OF_LIGHT:
        energy = collision_energy(velocity, projectile_mass, target_mass)
        return float(np.interp(energy, table[:, 0], table[:, 1], left=0.0, right=0.0)) * velocity, energy
    sigma_thermal = math.sqrt(BOLTZMANN * max(temperature, 0.0) / target_mass)
    generator = np.random.default_rng(1)
    targets = generator.normal(0.0, 1.0, size=(THERMAL_SAMPLES, 3)) * sigma_thermal
    relative = np.linalg.norm(np.array([0.0, velocity, 0.0]) - targets, axis=1)
    energies = 0.5 * reduced * relative**2 / EV
    for rotational_temperature in rotational:
        energies = energies + generator.exponential(BOLTZMANN * rotational_temperature / EV, size=THERMAL_SAMPLES)
    sigma = np.interp(energies, table[:, 0], table[:, 1], left=0.0, right=0.0)
    return float(np.mean(sigma * relative)), float(np.mean(energies))


def cross_section(database: Database, first: str, second: str, products: Optional[list[str]]) -> Optional[np.ndarray]:
    """Reaction cross-section (products in the order of the reaction definition) or the total cross-section (products None)"""
    wanted = canonical_pair(f'{first}-{second}')
    for name, pair in database.collision_pairs.items():
        if canonical_pair(name) != wanted:
            continue
        if products is None:
            parts = pair.of_kind(XSecKind.EFFECTIVE) or pair.of_kind(XSecKind.ELASTIC)
            return parts[0].data if parts else None
        key = '-'.join(products)
        for xsec in pair.of_kind(XSecKind.REACTION):
            if xsec.key == key:
                return xsec.data
    return None


def evaluate_check(directory: pathlib.Path, database_path: Optional[pathlib.Path] = None) -> list[Comparison]:
    params = read_ini(directory / 'parameter.ini', directory / 'DSMC.ini')
    analyze = read_ini(directory / 'analyze.ini')
    references = [name.strip() for name in analyze.get('compare_data_file_reference', '').split(',') if name.strip()]
    if not references:
        raise RegressionCheckError(f'{directory.name}: no compare_data_file_reference in analyze.ini')

    if database_path is None:
        name = params.get('particles-collxsec-database') or params.get('particles-species-database')
        if name is None:
            raise RegressionCheckError(f'{directory.name}: no cross-section database in parameter.ini')
        database_path = directory / name
        if not database_path.is_file():
            copied = read_ini(directory / 'command_line.ini').get('database')  # reggie copies the database into the run directory
            database_path = directory / copied if copied else database_path
    if params.get('calcreacrates', 'f').lower() not in ('t', 'true', '.true.'):
        raise RegressionCheckError(f'{directory.name}: no reaction rates in the reference (CalcReacRates = F)')
    database = read_database(database_path)

    species: dict[int, SpeciesSetup] = {}
    for number in range(1, int(number_of(params.get('part-nspecies'), 0.0) or 0) + 1):
        prefix = f'part-species{number}-'
        name = params.get(prefix + 'speciesname', '')
        entry = database.species.get(name)
        attributes = entry.attributes if entry is not None else {}
        mass = number_of(params.get(prefix + 'massic'), attributes.get('MassIC'))
        temperature = number_of(params.get(prefix + 'init1-mwtemperatureic'), 0.0)
        species[number] = SpeciesSetup(
            name=name,
            mass=mass,
            heat=number_of(params.get(prefix + 'heatofformation_k'), attributes.get('HeatOfFormation_K', 0.0)) or 0.0,
            space=params.get(prefix + 'init1-spaceic', '').lower(),
            distribution=params.get(prefix + 'init1-velocitydistribution', '').lower(),
            velocities=values_of(params.get(prefix + 'init1-veloic', '0')),
            density=number_of(params.get(prefix + 'init1-partdensity'), 0.0) or 0.0,
            temperature=temperature or 0.0,
            rotation=number_of(params.get(prefix + 'init1-temprot'), temperature) or 0.0,
            molecule=int(number_of(params.get(prefix + 'interactionid'), attributes.get('InteractionID', 0)) or 0) in (2, 20),
        )
    timestep = number_of(params.get('manualtimestep'), 0.0) or 0.0

    comparisons = []
    for number in range(1, int(params.get('dsmc-numofreactions', '0')) + 1):
        if params.get(f'dsmc-reaction{number}-reactionmodel', '').lower() != 'xsec':
            continue
        reactants = [index for index in indices(params.get(f'dsmc-reaction{number}-reactants', '')) if index > 0]
        products = [species[index].name for index in indices(params.get(f'dsmc-reaction{number}-products', '')) if index > 0]
        background = [index for index in reactants if species[index].space == 'background']
        beams = [index for index in reactants if species[index].distribution == 'constant' and species[index].space != 'background']
        if len(background) != 1 or len(beams) != 1:
            continue  # only background + monoenergetic projectile
        target, projectile = species[background[0]], species[beams[0]]
        if target.mass is None or projectile.mass is None:
            continue
        target_mass, projectile_mass = target.mass, projectile.mass
        data = cross_section(database, target.name, projectile.name, products)
        total = cross_section(database, target.name, projectile.name, None)
        reactions_of_pair = [
            cross_section(database, target.name, projectile.name, [species[i].name for i in indices(params.get(f'dsmc-reaction{other}-products', '')) if i > 0])
            for other in range(1, int(params.get('dsmc-numofreactions', '0')) + 1)
            if sorted(i for i in indices(params.get(f'dsmc-reaction{other}-reactants', '')) if i > 0) == sorted(reactants)
        ]
        heat = (sum(species[i].heat for i in indices(params.get(f'dsmc-reaction{number}-products', '')) if i > 0) - sum(species[i].heat for i in reactants)) * BOLTZMANN / EV
        equation = f'{target.name} + {projectile.name} -> {" + ".join(products)}'
        velocities = projectile.velocities
        if len(references) != len(velocities):
            continue  # several variations per reference file: not supported
        for reference, velocity in zip(references, velocities, strict=True):
            rates = read_rates(directory / reference, number)
            if rates is None:
                continue
            energy = collision_energy(velocity, projectile_mass, target_mass)
            if data is None:
                expected = float('nan')
            else:
                table = data
                if table[0, 1] > 0.0 and 0.0 < heat < table[0, 0]:
                    table = np.vstack([[heat, 0.0], table])  # PICLas prepends zero at the heat of reaction
                rotational = tuple(part.rotation for part in (target, projectile) if part.molecule)
                expected, _ = beam_rate(table, velocity, projectile_mass, target_mass, target.temperature, rotational)
            sigma_total = sum(float(np.interp(energy, part[:, 0], part[:, 1], left=0.0, right=0.0)) for part in [total, *reactions_of_pair] if part is not None)
            probability = target.density * sigma_total * velocity * timestep
            reference_rate = rates[number - 1]
            deviation = (reference_rate - expected) / expected if expected > 0.0 else None
            factor = (1.0 - math.exp(-probability)) / probability if probability > 0.0 else 1.0
            corrected = (reference_rate - expected * factor) / (expected * factor) if expected > 0.0 else None
            comparisons.append(Comparison(directory.name, reference, number, equation, energy, reference_rate, expected, deviation, probability, corrected))
    return comparisons
