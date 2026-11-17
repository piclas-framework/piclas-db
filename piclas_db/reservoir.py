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
"""Reservoir simulations with PICLas to validate a database ('piclas-db reservoir', WP4)

A reservoir simulation counts the reactions of a projectile species (e.g. electrons) with a background gas in a single cell
without performing them (Particles-DSMCReservoirSim*), as in the NIG_Reservoir regression checks of PICLas. The rate coefficient
PICLas reports (CalcReacRates) is compared with the rate coefficient expected from the cross-section in the database:

* beam (monoenergetic projectiles, velocityDistribution = constant): k = sigma(E) v with E = mu v^2 / 2 and a cold background
* Maxwell (projectiles and background at temperature T): k(T) = <sigma v> over the Maxwell distribution of the reduced mass

'generate' writes one directory per energy or temperature with a parameter.ini, a common hopr.ini for the single-cell mesh, a
run script and study.yaml; 'evaluate' reads the PartAnalyze.csv files and compares the rates.
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import csv
import math
import pathlib
from dataclasses import dataclass, field
from typing import Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import numpy as np
import yaml

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.compare import canonical_pair
from piclas_db.model import Database, XSecKind
from piclas_db.plot import BOLTZMANN, EV, rate_coefficient
# ==================================================================================================================================

CELL_LENGTH = 4.64e-6  # m, single cell as in the PICLas reservoir regression checks (volume 1e-16 m^3)
CELL_VOLUME = CELL_LENGTH**3
MAX_STEPS = 50_000
COLLISION_PROBABILITY = 0.01  # default maximum collision probability per time step
# PICLas computes collision probabilities as 1 - exp(-n sigma g dt), so the counted rate is lower than n sigma g by about half the
# collision probability (-2.5 % at 0.05, measured in a first Ar reservoir study); 0.01 keeps this below the statistical error.


class ReservoirError(Exception):
    """Study cannot be generated or evaluated"""


@dataclass
class ReactionCase:
    key: str  # products as in the database, e.g. 'ArIon1-electron-electron'
    products: list[str]


@dataclass
class Settings:
    background_density: float = 1.0e22  # m^-3
    projectile_density: float = 1.0e21  # m^-3
    background_temperature: float = 300.0  # K (beam mode)
    events: float = 1.0e4  # counted reactions aimed for at every point (statistical error about 1 %)
    collision_probability: float = COLLISION_PROBABILITY  # maximum collision probability per time step


@dataclass
class Point:
    name: str
    value: float  # energy [eV] (beam) or temperature [K] (Maxwell)
    velocity: Optional[float]  # projectile velocity (beam)
    timestep: float
    steps: int
    expected: dict[str, float] = field(default_factory=dict)  # expected rate coefficient per reaction key [m^3/s]
    events: dict[str, float] = field(default_factory=dict)  # expected number of counted reactions


def species_mass(database: Database, name: str) -> float:
    species = database.species.get(name)
    mass = species.attributes.get('MassIC') if species else None
    if not isinstance(mass, (int, float)):
        raise ReservoirError(f'MassIC of {name} not in the database (a reservoir study needs a complete species database)')
    return float(mass)


def find_pair(database: Database, pair: str) -> tuple[str, list[ReactionCase], np.ndarray, dict[str, np.ndarray]]:
    """Name of the pair in the database, its reactions, the total cross-section and the reaction cross-sections"""
    for name, collision_pair in database.collision_pairs.items():
        if canonical_pair(name) != canonical_pair(pair):
            continue
        reactions = [ReactionCase(key=xsec.key, products=xsec.key.split('-')) for xsec in collision_pair.of_kind(XSecKind.REACTION)]
        cross_sections = {xsec.key: xsec.data for xsec in collision_pair.of_kind(XSecKind.REACTION)}
        grid = np.unique(np.concatenate([xsec.data[:, 0] for xsec in collision_pair.cross_sections if xsec.data.ndim == 2]))
        total = np.zeros_like(grid)
        for xsec in collision_pair.cross_sections:
            if xsec.data.ndim == 2 and xsec.kind is not XSecKind.SPECTRUM:
                total += np.interp(grid, xsec.data[:, 0], xsec.data[:, 1], left=0.0, right=0.0)
        return name, reactions, np.column_stack([grid, total]), cross_sections
    raise ReservoirError(f'collision pair {pair} not in the database')


def heat_of_reaction(database: Database, reactants: list[str], products: list[str]) -> Optional[float]:
    """Energy needed for the reaction in eV from the heats of formation (HeatOfFormation_K), None if they are missing"""
    total = 0.0
    for sign, names in ((-1.0, reactants), (1.0, products)):
        for name in names:
            species = database.species.get(name)
            value = species.attributes.get('HeatOfFormation_K', 0.0 if name == 'electron' else None) if species else None
            if not isinstance(value, (int, float)):
                return None
            total += sign * float(value)
    return total * BOLTZMANN / EV


def as_used_by_piclas(database: Database, data: np.ndarray, reactants: list[str], products: list[str]) -> np.ndarray:
    """Reaction cross-section as PICLas uses it: if the first value is not zero, PICLas prepends zero at the heat of reaction"""
    if data[0, 1] <= 0.0:
        return data
    threshold = heat_of_reaction(database, reactants, products)
    if threshold is None or threshold <= 0.0 or threshold >= data[0, 0]:
        return data
    return np.vstack([[threshold, 0.0], data])


def plan_point(name: str, rates: dict[str, float], collision_frequency: float, settings: Settings) -> tuple[float, int, dict[str, float]]:
    """Time step (collision probability per step limited) and number of steps (enough counted reactions for the rarest reaction)"""
    timestep = settings.collision_probability / max(collision_frequency, 1.0)
    particles = settings.projectile_density * CELL_VOLUME
    positive = [rate for rate in rates.values() if rate > 0.0]
    if not positive:
        steps = 100
    else:
        needed_time = settings.events / (particles * settings.background_density * min(positive))
        steps = min(MAX_STEPS, max(100, math.ceil(needed_time / timestep)))
    events = {key: particles * settings.background_density * rate * timestep * steps for key, rate in rates.items()}
    return timestep, steps, events


def plan(
    database: Database,
    pair: str,
    projectile: Optional[str],
    energies: list[float],
    temperatures: list[float],
    settings: Settings,
    selected: Optional[list[str]] = None,
) -> dict:
    """Study definition (written to study.yaml)"""
    name, reactions, total, cross_sections = find_pair(database, pair)
    if not reactions:
        raise ReservoirError(f'{name} has no reaction cross-sections (REACTION group)')
    first, _, second = name.partition('-')
    projectile = projectile or (second if second == 'electron' or 'Ion' in second else first)
    if projectile not in (first, second):
        raise ReservoirError(f'projectile {projectile} is not part of {name}')
    target = second if projectile == first else first
    mass_projectile, mass_target = species_mass(database, projectile), species_mass(database, target)
    reduced = mass_projectile * mass_target / (mass_projectile + mass_target)

    skipped = []
    if selected:
        unknown = sorted(set(selected) - {reaction.key for reaction in reactions})
        if unknown:
            raise ReservoirError(f'reaction(s) {", ".join(unknown)} not in {name}')
        reactions = [reaction for reaction in reactions if reaction.key in selected]
    usable = []
    for reaction in reactions:
        missing = [product for product in reaction.products if product not in database.species]
        if missing:
            skipped.append(f'{reaction.key}: species {", ".join(missing)} not in the database')
        else:
            usable.append(reaction)
    if not usable:
        raise ReservoirError(f'no reaction of {name} can be simulated: ' + '; '.join(skipped))
    reactions = usable
    species = [target, projectile]
    for reaction in reactions:
        species += [product for product in reaction.products if product not in species]
    for product in species:
        species_mass(database, product)
    cross_sections = {reaction.key: as_used_by_piclas(database, cross_sections[reaction.key], [target, projectile], reaction.products) for reaction in reactions}

    points = []
    for energy in energies:
        velocity = math.sqrt(2.0 * energy * EV / reduced)
        rates = {key: float(np.interp(energy, data[:, 0], data[:, 1], left=0.0, right=0.0)) * velocity for key, data in cross_sections.items()}
        frequency = settings.background_density * float(np.interp(energy, total[:, 0], total[:, 1], left=0.0, right=0.0)) * velocity
        timestep, steps, events = plan_point(f'E{energy:g}eV', rates, frequency, settings)
        points.append(Point(f'E_{energy:g}eV', energy, velocity, timestep, steps, rates, events))
    for temperature in temperatures:
        rates = {key: float(rate_coefficient(data, np.array([temperature]), reduced)[0]) for key, data in cross_sections.items()}
        mean_speed = math.sqrt(8.0 * BOLTZMANN * temperature / (math.pi * reduced))
        frequency = settings.background_density * float(rate_coefficient(total, np.array([temperature]), reduced)[0]) + settings.background_density * 1.0e-30 * mean_speed
        timestep, steps, events = plan_point(f'T{temperature:g}K', rates, frequency, settings)
        points.append(Point(f'T_{temperature:g}K', temperature, None, timestep, steps, rates, events))

    return {
        'pair': name,
        'mode': 'beam' if energies else 'maxwell',
        'target': target,
        'projectile': projectile,
        'species': species,
        'reactions': [{'key': reaction.key, 'products': reaction.products} for reaction in reactions],
        'skipped': skipped,
        'settings': vars(settings),
        'points': [vars(point) for point in points],
    }


# ----------------------------------------------------------------------------------------------------------------------------------
# Input files
# ----------------------------------------------------------------------------------------------------------------------------------
HOPR = """! Single-cell mesh for reservoir simulations (as in the PICLas NIG_Reservoir regression checks), create with: hopr hopr.ini
ProjectName   = cube
Debugvisu     = F
Mode          = 1
nZones        = 1
Corner        = (/0.,0.,0.,,{L},0.,0.,,{L},{L},0.,,0.,{L},0.,,0.,0.,{L},,{L},0.,{L},,{L},{L},{L},,0.,{L},{L}/)
nElems        = (/1,1,1/)
BCIndex       = (/1,1,1,1,1,1/)
elemtype      = 108
BoundaryName  = BC_adiabat
BoundaryType  = (/4,0,0,0/)
"""


def parameter_ini(study: dict, point: dict, database_path: str) -> str:
    settings = study['settings']
    species = study['species']
    index = {name: number for number, name in enumerate(species, start=1)}
    beam = study['mode'] == 'beam'
    temperature = settings['background_temperature'] if beam else point['value']
    analyze_time = point['timestep'] * point['steps']
    lines = [
        f'! Reservoir simulation generated by piclas-db: {study["pair"]}, {point["name"]}',
        'N             = 1',
        'NAnalyze      = 1',
        'ProjectName   = reservoir',
        'MeshFile      = ../cube_mesh.h5',
        'TrackingMethod = triatracking',
        'Logging       = F',
        f'Part-AnalyzeStep = {point["steps"]}',
        'CalcReacRates    = T',
        f'IterDisplayStep  = {max(1, point["steps"] // 10)}',
        f'ManualTimeStep   = {point["timestep"]:.6E}',
        f'tend             = {analyze_time:.6E}',
        f'Analyze_dt       = {analyze_time:.6E}',
        'PIC-DoDeposition    = F',
        'PIC-DoInterpolation = F',
        'UseDSMC                           = T',
        'Particles-DSMC-CollisMode         = 3',
        'Part-NumberOfRandomSeeds          = 2',
        'Particles-RandomSeed1             = 1',
        'Particles-RandomSeed2             = 2',
        'Particles-HaloEpsVelo             = 3E8',
        'Particles-DSMC-CalcQualityFactors = F',
        'Particles-CollXSec-NullCollision  = T',
        'Particles-DSMC-ElectronicModel    = 0',
        'Particles-DSMC-VibRelaxProb       = 0.',
        'Particles-DSMCReservoirSim        = T',
        'Particles-DSMCReservoirSimRate    = T',
        'Particles-DSMCReservoirStatistic  = T',
        'Part-maxParticleNumber    = 500000',
        'Part-nBounds              = 1',
        'Part-Boundary1-SourceName = BC_adiabat',
        'Part-Boundary1-Condition  = reflective',
        f'Part-nSpecies = {len(species)}',
        f'Particles-Species-Database = {database_path}',
        'Part-Species$-MacroParticleFactor = 1',
    ]
    for name, number in index.items():
        lines.append(f'Part-Species{number}-SpeciesName = {name}')
    target, projectile = index[study['target']], index[study['projectile']]
    lines += [
        f'Part-Species{target}-nInits = 1',
        f'Part-Species{target}-Init1-SpaceIC              = background',
        f'Part-Species{target}-Init1-velocityDistribution = maxwell_lpn',
        f'Part-Species{target}-Init1-PartDensity          = {settings["background_density"]:.6E}',
        f'Part-Species{target}-Init1-VeloIC               = 0.',
        f'Part-Species{target}-Init1-VeloVecIC            = (/0.,1.,0./)',
        f'Part-Species{target}-Init1-MWTemperatureIC      = {temperature:g}',
        f'Part-Species{target}-Init1-TempVib              = {temperature:g}',
        f'Part-Species{target}-Init1-TempRot              = {temperature:g}',
        f'Part-Species{target}-Init1-TempElec             = {temperature:g}',
        f'Part-Species{projectile}-nInits = 1',
        f'Part-Species{projectile}-Init1-SpaceIC              = cell_local',
        f'Part-Species{projectile}-Init1-velocityDistribution = {"constant" if beam else "maxwell_lpn"}',
        f'Part-Species{projectile}-Init1-PartDensity          = {settings["projectile_density"]:.6E}',
        f'Part-Species{projectile}-Init1-VeloIC               = {point["velocity"] if beam else 0.0:.8g}',
        f'Part-Species{projectile}-Init1-VeloVecIC            = (/0.,1.,0./)',
        f'Part-Species{projectile}-Init1-MWTemperatureIC      = {temperature:g}',
        f'Part-Species{projectile}-UseCollXSec = T',
        f'DSMC-NumOfReactions = {len(study["reactions"])}',
    ]
    for number, reaction in enumerate(study['reactions'], start=1):
        products = [index[name] for name in reaction['products']] + [0] * (4 - len(reaction['products']))
        lines += [
            f'! {study["target"]} + {study["projectile"]} -> {" + ".join(reaction["products"])}',
            f'DSMC-Reaction{number}-ReactionModel = XSec',
            f'DSMC-Reaction{number}-Reactants     = (/{target},{projectile},0/)',
            f'DSMC-Reaction{number}-Products      = (/{",".join(str(product) for product in products)}/)',
        ]
    return '\n'.join(lines) + '\n'


RUN_SCRIPT = """#!/bin/bash
# Reservoir study generated by piclas-db: runs PICLas for every point, then evaluate with
#   piclas-db reservoir --evaluate {directory}
set -e
cd "$(dirname "$0")"
PICLAS=${{PICLAS:-piclas}}          # path to the PICLas binary (built with PICLAS_TIMEDISCMETHOD=DSMC)
if [ ! -f cube_mesh.h5 ]; then
  if command -v hopr >/dev/null; then hopr hopr.ini; else pyhope hopr.ini; fi
fi
for point in {points}; do
  (cd "$point" && "$PICLAS" parameter.ini > std.out 2>&1 && echo "$point done")
done
"""


def write_study(study: dict, directory: pathlib.Path, database_path: pathlib.Path) -> None:
    if directory.exists() and any(directory.iterdir()):
        raise ReservoirError(f'directory is not empty: {directory}')
    directory.mkdir(parents=True, exist_ok=True)
    study = dict(study, database=str(database_path.resolve()))
    (directory / 'study.yaml').write_text(yaml.safe_dump(study, sort_keys=False, width=1000))
    (directory / 'hopr.ini').write_text(HOPR.format(L=f'{CELL_LENGTH:g}'))
    for point in study['points']:
        (directory / point['name']).mkdir()
        (directory / point['name'] / 'parameter.ini').write_text(parameter_ini(study, point, str(database_path.resolve())))
    run = directory / 'run.sh'
    run.write_text(RUN_SCRIPT.format(directory=directory, points=' '.join(point['name'] for point in study['points'])))
    run.chmod(0o755)


# ----------------------------------------------------------------------------------------------------------------------------------
# Evaluation
# ----------------------------------------------------------------------------------------------------------------------------------
@dataclass
class Result:
    point: str
    value: float
    reaction: str
    expected: float
    simulated: Optional[float]
    statistical: Optional[float]  # relative standard deviation from the expected number of counted reactions
    deviation: Optional[float]
    passed: Optional[bool]
    systematic: bool = False  # within the tolerance, but more than three standard deviations from the expected value


def read_rates(path: pathlib.Path, count: int) -> Optional[list[float]]:
    """Reaction rate coefficients of the last line of PartAnalyze.csv ('NNN-Reaction001', ...)"""
    if not path.is_file():
        return None
    with path.open(newline='') as file:
        rows = list(csv.reader(file))
    if len(rows) < 2:
        return None
    header, last = rows[0], rows[-1]
    rates = []
    for number in range(1, count + 1):
        column = next((i for i, name in enumerate(header) if name.strip().endswith(f'-Reaction{number:03d}')), None)
        if column is None:
            raise ReservoirError(f'{path}: column Reaction{number:03d} missing (CalcReacRates = T?)')
        rates.append(float(last[column]))
    return rates


def evaluate(directory: pathlib.Path, tolerance: float) -> list[Result]:
    study_file = directory / 'study.yaml'
    if not study_file.is_file():
        raise ReservoirError(f'{directory} is not a reservoir study (study.yaml missing)')
    study = yaml.safe_load(study_file.read_text())
    keys = [reaction['key'] for reaction in study['reactions']]
    results = []
    for point in study['points']:
        rates = read_rates(directory / point['name'] / 'PartAnalyze.csv', len(keys))
        for number, key in enumerate(keys):
            expected = float(point['expected'][key])
            events = float(point['events'][key])
            statistical = 1.0 / math.sqrt(events) if events > 0.0 else None
            if rates is None:
                results.append(Result(point['name'], point['value'], key, expected, None, statistical, None, None))
                continue
            simulated = rates[number]
            if expected <= 0.0:
                passed = not simulated > 0.0  # below the threshold no reaction may occur
                results.append(Result(point['name'], point['value'], key, expected, simulated, None, None, passed))
                continue
            deviation = (simulated - expected) / expected
            limit = max(tolerance, 3.0 * statistical) if statistical else tolerance
            systematic = statistical is not None and abs(deviation) > 3.0 * statistical
            results.append(Result(point['name'], point['value'], key, expected, simulated, statistical, deviation, abs(deviation) <= limit, systematic))
    return results
