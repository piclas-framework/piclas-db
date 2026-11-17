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
import argparse
import pathlib

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import matplotlib.pyplot as plt
import numpy as np

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.readers import DatabaseReadError, read_database
from piclas_db.reservoir import ReservoirError, Result, Settings, evaluate, plan, write_study
# ==================================================================================================================================


def values(texts: list[str]) -> list[float]:
    """Numbers, or start:stop:count for logarithmically spaced values"""
    result: list[float] = []
    for text in texts:
        if ':' in text:
            start, stop, count = (float(part) for part in text.split(':'))
            result += np.logspace(np.log10(start), np.log10(stop), int(count)).tolist()
        else:
            result.append(float(text))
    if any(value <= 0.0 for value in result):
        raise ValueError('energies and temperatures must be positive')
    return result


def generate(args: argparse.Namespace) -> int:
    if not args.database or not args.pair or not args.output or bool(args.energies) == bool(args.temperatures):
        print('ERROR: give DATABASE, --pair, -o and either --energies (beam) or --temperatures (Maxwell)')
        return 1
    settings = Settings(background_density=args.background_density, projectile_density=args.projectile_density, events=args.events)
    try:
        database = read_database(args.database)
        study = plan(database, args.pair, args.projectile, values(args.energies or []), values(args.temperatures or []), settings, args.reactions)
        write_study(study, pathlib.Path(args.output), pathlib.Path(args.database))
    except (DatabaseReadError, ReservoirError, ValueError) as e:
        print(f'ERROR: {e}')
        return 1
    print(f'Reservoir study {study["pair"]} ({study["mode"]}, projectile {study["projectile"]}) in {args.output}:')
    for reaction in study['reactions']:
        print(f'  reaction  {study["target"]} + {study["projectile"]} -> {" + ".join(reaction["products"])}')
    for line in study['skipped']:
        print(f'  skipped   {line}')
    for point in study['points']:
        positive = [events for events in point['events'].values() if events > 0.0]
        note = f', at least {min(positive):.0f} counted reactions' if positive else ', below all thresholds'
        if positive and min(positive) < 0.5 * settings.events:
            note += ' (fewer than aimed for: increase --background-density or accept a larger statistical error)'
        print(f'  {point["name"]:14s} {point["steps"]:6d} steps of {point["timestep"]:.2e} s{note}')
    print(f'Run: PICLAS=<path to piclas> {args.output}/run.sh, then: piclas-db reservoir --evaluate {args.output}')
    return 0


def plot_results(results: list[Result], mode: str, output: pathlib.Path) -> None:
    figure, axis = plt.subplots(figsize=(8, 5))
    colors = plt.rcParams['axes.prop_cycle'].by_key()['color']
    for index, key in enumerate(dict.fromkeys(result.reaction for result in results)):
        rows = sorted((result for result in results if result.reaction == key), key=lambda result: result.value)
        x = [result.value for result in rows]
        axis.plot(x, [result.expected for result in rows], '-', color=colors[index % len(colors)], label=f'{key} (database)')
        simulated = [(result.value, result.simulated) for result in rows if result.simulated]
        if simulated:
            axis.plot(*zip(*simulated, strict=True), 'o', color=colors[index % len(colors)], label=f'{key} (PICLas)')
    axis.set_xscale('log')
    axis.set_yscale('log')
    axis.set_xlabel('collision energy E [eV]' if mode == 'beam' else 'temperature T [K]')
    axis.set_ylabel('rate coefficient k [m³/s]')
    axis.grid(True, which='both', alpha=0.3)
    axis.legend(fontsize='small')
    figure.tight_layout()
    figure.savefig(output, dpi=150)


def run(args: argparse.Namespace) -> int:
    """Generate a reservoir study, or evaluate a finished one (--evaluate DIRECTORY)"""
    if not args.evaluate:
        return generate(args)
    directory = pathlib.Path(args.evaluate)
    try:
        results = evaluate(directory, args.tolerance)
    except ReservoirError as e:
        print(f'ERROR: {e}')
        return 1
    print(f'{"point":14s} {"reaction":32s} {"database":>11s} {"PICLas":>11s} {"deviation":>10s} {"stat.":>7s}')
    for result in results:
        simulated = f'{result.simulated:11.3e}' if result.simulated is not None else '    not run'
        deviation = f'{result.deviation:+10.2%}' if result.deviation is not None else ' ' * 10
        statistical = f'{result.statistical:7.2%}' if result.statistical is not None else ' ' * 7
        status = {None: '', True: 'ok', False: 'FAILED'}[result.passed]
        print(f'{result.point:14s} {result.reaction:32s} {result.expected:11.3e} {simulated} {deviation} {statistical} {status}')
    import yaml  # noqa: PLC0415

    mode = yaml.safe_load((directory / 'study.yaml').read_text())['mode']
    plot_results(results, mode, directory / 'rates.png')
    failed = sum(result.passed is False for result in results)
    missing = sum(result.simulated is None for result in results)
    print(f'{len(results) - failed - missing} ok, {failed} failed, {missing} not run (tolerance {args.tolerance:.0%} or 3 standard deviations); plot: {directory / "rates.png"}')
    return 1 if failed or missing else 0
