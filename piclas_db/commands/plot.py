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
import numpy as np

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.plot import PlotError, Source, contents, plot_cross_sections, plot_levels
from piclas_db.readers import DatabaseReadError
from piclas_db.sources.any import read_any
# ==================================================================================================================================


def temperatures(text: str) -> np.ndarray:
    """'1e3:1e5' (60 logarithmically spaced values) or 'start:stop:count'"""
    parts = [float(part) for part in text.split(':')]
    if len(parts) not in (2, 3) or parts[0] <= 0.0 or parts[1] <= parts[0]:
        raise ValueError(f'temperatures must be start:stop[:count] with 0 < start < stop, got {text!r}')
    return np.logspace(np.log10(parts[0]), np.log10(parts[1]), int(parts[2]) if len(parts) == 3 else 60)


def run(args: argparse.Namespace) -> int:
    """Plot cross-sections, rate coefficients or electronic levels from database files, ASCII tables or original downloads"""
    if args.label and len(args.label) != len(args.sources):
        print('ERROR: give one --label per source')
        return 1
    try:
        sources = [Source(label=args.label[index] if args.label else pathlib.Path(path).name, database=read_any(path, species=args.species)) for index, path in enumerate(args.sources)]
    except DatabaseReadError as e:
        print(f'ERROR: {e}')
        return 1

    if args.list or not (args.pair or args.species):
        print('\n'.join(contents(sources)))
        return 0 if args.list else 1

    try:
        if args.pair:
            figure = plot_cross_sections(sources, args.pair, kinds=args.kind, key=args.key, compare=args.compare, rate=args.rate, temperatures=temperatures(args.temperatures))
        else:
            figure = plot_levels(sources, args.species)
    except (PlotError, ValueError) as e:
        print(f'ERROR: {e}')
        return 1
    output = pathlib.Path(args.output)
    figure.savefig(output, dpi=150)
    print(f'Plot written to {output}')
    return 0
