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
"""Plots of cross-sections, rate coefficients and electronic levels from any combination of sources ('piclas-db plot')"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
from dataclasses import dataclass
from typing import Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import matplotlib

matplotlib.use('Agg')  # files only, no display needed (e.g. on HPC login nodes)
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.compare import canonical_pair, effective_kind, matching_key  # noqa: E402
from piclas_db.model import CrossSection, Database  # noqa: E402
from piclas_db.reference import EV_TO_K  # noqa: E402
# ==================================================================================================================================

BOLTZMANN = 1.380649e-23  # J/K
ELECTRON_MASS = 9.1093837139e-31  # kg
EV = 1.602176634e-19  # J
LINESTYLES = ('-', '--', ':', '-.')


class PlotError(Exception):
    """Nothing to plot"""


@dataclass
class Source:
    label: str
    database: Database


# ----------------------------------------------------------------------------------------------------------------------------------
# Rate coefficients
# ----------------------------------------------------------------------------------------------------------------------------------
def rate_coefficient(data: np.ndarray, temperatures: np.ndarray, reduced_mass: float, points: int = 4000) -> np.ndarray:
    """Maxwellian rate coefficient k(T) = sqrt(8/(pi mu)) (k_B T)^(-3/2) int sigma(E) E exp(-E/(k_B T)) dE in m^3/s

    data: (n_rows, 2) collision energy [eV] and cross-section [m^2]; the cross-section is linearly interpolated and zero outside the table
    """
    energy_ev = data[:, 0]
    rates = np.empty_like(temperatures, dtype=np.float64)
    for index, temperature in enumerate(temperatures):
        kt = BOLTZMANN * temperature
        upper = min(float(energy_ev[-1]), 50.0 * kt / EV)  # exp(-50) is negligible
        grid = np.linspace(float(energy_ev[0]), max(upper, float(energy_ev[0])), points)
        sigma = np.interp(grid, energy_ev, data[:, 1], left=0.0, right=0.0)
        energy = grid * EV
        integral = np.trapezoid(sigma * energy * np.exp(-energy / kt), energy)
        rates[index] = np.sqrt(8.0 / (np.pi * reduced_mass)) * kt**-1.5 * integral
    return rates


def reduced_mass(pair: str, sources: list[Source]) -> float:
    first, _, second = pair.partition('-')
    if 'electron' in (first, second):
        return ELECTRON_MASS
    masses = {}
    for source in sources:
        for name in (first, second):
            species = source.database.species.get(name)
            mass = species.attributes.get('MassIC') if species else None
            if isinstance(mass, float):
                masses.setdefault(name, mass)
    if len(masses) < 2:
        raise PlotError(f'rate coefficients of {pair} need the masses of {first} and {second} (MassIC in one of the sources)')
    return masses[first] * masses[second] / (masses[first] + masses[second])


# ----------------------------------------------------------------------------------------------------------------------------------
# Selection
# ----------------------------------------------------------------------------------------------------------------------------------
def entry_label(xsec: CrossSection) -> str:
    kind = effective_kind(xsec).value
    return kind if xsec.group is None else f'{kind} {xsec.key}'


def select(sources: list[Source], pair: str, kinds: list[str], key: Optional[str]) -> dict[tuple[str, str], dict[str, CrossSection]]:
    """Cross-sections of the pair per matching key and source label"""
    wanted = canonical_pair(pair)
    selected: dict[tuple[str, str], dict[str, CrossSection]] = {}
    for source in sources:
        for name, collision_pair in source.database.collision_pairs.items():
            if canonical_pair(name) != wanted:
                continue
            for xsec in collision_pair.cross_sections:
                if kinds and effective_kind(xsec).value not in kinds:
                    continue
                if key and key not in xsec.key:
                    continue
                selected.setdefault(matching_key(xsec), {})[source.label] = xsec
    if not selected:
        raise PlotError(f'no cross-sections of {pair} in the sources' + (' with the given filters' if kinds or key else ''))
    return selected


def deviation(reference: np.ndarray, other: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Relative deviation of other from reference on the union of both grids, where the cross-section is significant"""
    low, high = max(reference[0, 0], other[0, 0]), min(reference[-1, 0], other[-1, 0])
    energy = np.union1d(reference[:, 0], other[:, 0])
    energy = energy[(energy >= low) & (energy <= high) & (energy > 0.0)]
    sigma_a = np.interp(energy, reference[:, 0], reference[:, 1])
    sigma_b = np.interp(energy, other[:, 0], other[:, 1])
    significant = np.maximum(sigma_a, sigma_b) > 0.01 * max(float(np.max(sigma_a, initial=0.0)), float(np.max(sigma_b, initial=0.0)), 1.0e-300)
    significant &= sigma_a > 0.0
    return energy[significant], (sigma_b[significant] - sigma_a[significant]) / sigma_a[significant]


# ----------------------------------------------------------------------------------------------------------------------------------
# Figures
# ----------------------------------------------------------------------------------------------------------------------------------
def plot_cross_sections(
    sources: list[Source],
    pair: str,
    kinds: Optional[list[str]] = None,
    key: Optional[str] = None,
    compare: bool = False,
    rate: bool = False,
    temperatures: Optional[np.ndarray] = None,
) -> Figure:
    selected = select(sources, pair, kinds or [], key)
    labels = [source.label for source in sources]
    figure, axes = plt.subplots(2 if compare and len(sources) > 1 else 1, 1, figsize=(8, 7 if compare else 5), sharex=True, squeeze=False)
    main, below = axes[0, 0], axes[-1, 0] if compare and len(sources) > 1 else None
    colors = plt.rcParams['axes.prop_cycle'].by_key()['color']
    grid = temperatures if temperatures is not None else np.logspace(3, 5, 60)
    mass = reduced_mass(pair, sources) if rate else ELECTRON_MASS

    for index, (_, by_source) in enumerate(sorted(selected.items())):
        color = colors[index % len(colors)]
        reference_label = next(label for label in labels if label in by_source)
        for label, xsec in by_source.items():
            style = LINESTYLES[labels.index(label) % len(LINESTYLES)]
            name = f'{entry_label(xsec)} ({label})' if len(sources) > 1 else entry_label(xsec)
            data = xsec.data
            if rate:
                x, y = grid, rate_coefficient(data, grid, mass)
            else:
                positive = (data[:, 0] > 0.0) & (data[:, 1] > 0.0)
                x, y = data[positive, 0], data[positive, 1]
            main.plot(x, y, style, color=color, label=name)
            if below is not None and label != reference_label and not rate:
                energy, relative = deviation(by_source[reference_label].data, data)
                below.plot(energy, 100.0 * relative, style, color=color, label=name)

    main.set_xscale('log')
    main.set_yscale('log')
    if rate:
        top = max((float(np.max(line.get_ydata())) for line in main.get_lines()), default=1.0)
        main.set_ylim(top * 1.0e-8, top * 3.0)  # rates far below the maximum are irrelevant
    main.set_ylabel('rate coefficient k(T) [m³/s]' if rate else 'cross-section σ [m²]')
    main.set_title(f'{pair}' + (' – Maxwellian rate coefficients' if rate else ''))
    main.grid(True, which='both', alpha=0.3)
    main.legend(fontsize='small', ncol=2)
    if below is not None:
        below.axhline(0.0, color='black', linewidth=0.8)
        below.set_ylabel(f'deviation from {labels[0]} [%]')
        below.grid(True, which='both', alpha=0.3)
        if rate:
            below.set_visible(False)
    (below if below is not None and not rate else main).set_xlabel('temperature T [K]' if rate else 'collision energy E [eV]')
    figure.tight_layout()
    return figure


def plot_levels(sources: list[Source], species: str) -> Figure:
    """Cumulative number of states (sum of degeneracies) over the level energy: unit errors and missing levels stand out"""
    figure, axis = plt.subplots(figsize=(8, 5))
    found = False
    for index, source in enumerate(sources):
        entry = source.database.species.get(species)
        if entry is None or entry.electronic_levels is None:
            continue
        found = True
        levels = entry.electronic_levels[np.argsort(entry.electronic_levels[:, 1], kind='stable')]
        levels = levels[levels[:, 1] < 1.0e10]  # dummy levels of species with only a ground state
        energy_ev = levels[:, 1] / EV_TO_K
        axis.step(energy_ev, np.cumsum(levels[:, 0]), where='post', linestyle=LINESTYLES[index % len(LINESTYLES)], label=f'{source.label} ({len(levels)} levels)')
    if not found:
        raise PlotError(f'no electronic levels of {species} in the sources')
    axis.set_xlabel('level energy [eV]')
    axis.set_ylabel('cumulative degeneracy Σ g')
    axis.set_yscale('log')
    axis.set_title(f'{species} – electronic levels')
    axis.grid(True, which='both', alpha=0.3)
    axis.legend(fontsize='small')
    figure.tight_layout()
    return figure


def contents(sources: list[Source]) -> list[str]:
    lines = []
    for source in sources:
        lines.append(f'{source.label}:')
        for name, pair in source.database.collision_pairs.items():
            lines.append(f'  --pair {name}: ' + ', '.join(sorted({entry_label(xsec) for xsec in pair.cross_sections})))
        levels = [name for name, species in source.database.species.items() if species.electronic_levels is not None]
        if levels:
            lines.append(f'  --species {" ".join(levels)}')
    return lines
