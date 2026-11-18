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
from typing import Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import numpy as np

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.compare import canonical_pair
from piclas_db.model import CrossSection
from piclas_db.store import Store
from piclas_db.plot import Part, parts_of, plot_parts_with, PlotError, Source, contents, plot_cross_sections, plot_levels
from piclas_db.readers import DatabaseReadError
from piclas_db.sources.any import read_any
# ==================================================================================================================================


def temperatures(text: str) -> np.ndarray:
    """'1e3:1e5' (60 logarithmically spaced values) or 'start:stop:count'"""
    parts = [float(part) for part in text.split(':')]
    if len(parts) not in (2, 3) or parts[0] <= 0.0 or parts[1] <= parts[0]:
        raise ValueError(f'temperatures must be start:stop[:count] with 0 < start < stop, got {text!r}')
    return np.logspace(np.log10(parts[0]), np.log10(parts[1]), int(parts[2]) if len(parts) == 3 else 60)


def full_data(source: str, store: Store) -> Optional[np.ndarray]:
    """All data of the extraction a part comes from (None if it is not in the store)"""
    from piclas_db.literature import LiteratureError, find_extraction, read_extraction  # noqa: PLC0415

    try:
        return read_extraction(find_extraction(store, source))
    except (LiteratureError, OSError, ValueError):
        return None


def plot_combined(args: argparse.Namespace, sources: list[Source]) -> int:
    """One figure per combined dataset (several extractions in energy ranges): parts, their full source data from the store, seams"""
    store = Store(args.store)
    output = pathlib.Path(args.output)
    written = 0
    for source in sources:
        for pair in source.database.collision_pairs.values():
            if args.pair and canonical_pair(pair.name) != canonical_pair(args.pair):
                continue
            for xsec in pair.cross_sections:
                parts = parts_of(xsec)
                if not parts or (args.key and args.key not in xsec.key):
                    continue
                missing = []
                for part in parts:
                    part.full = full_data(part.source, store)
                    if part.full is None:
                        missing.append(part.source)
                name = f'{pair.name}/' + (f'{xsec.group}/' if xsec.group else '') + xsec.key
                figure = plot_parts_with(xsec, parts, f'{name} ({source.label})')
                target = output if written == 0 else output.with_name(f'{output.stem}-{written + 1}{output.suffix}')
                figure.savefig(target, dpi=150)
                print(f'{name}: {len(parts)} parts -> {target}' + (f' (sources not in the store, ranges only: {", ".join(missing)})' if missing else ''))
                written += 1
    if not written:
        print('No combined datasets (built from several parts) found' + (f' for {args.pair}' if args.pair else ''))
        return 1
    return 0


def explain(data: np.ndarray, candidates: dict[str, np.ndarray]) -> list[Optional[str]]:
    """For every point of a dataset the first candidate source with the same energy and cross-section (to float32 precision)"""
    found: list[Optional[str]] = []
    for energy, sigma in data.tolist():
        match = None
        for name, source in candidates.items():
            same = np.isclose(source[:, 0], energy, rtol=1.0e-6, atol=0.0) & np.isclose(source[:, 1], sigma, rtol=1.0e-6, atol=1.0e-40)
            if np.any(same):
                match = name
                break
        found.append(match)
    return found


def plot_explained(args: argparse.Namespace, sources: list[Source]) -> int:
    """Which source each point of an existing dataset comes from (e.g. SpeciesDatabase.h5 against extractions from papers): the parts
    of a combined dataset are found from the numbers, and a recipe entry with these parts is suggested"""
    store = Store(args.store)
    candidates: dict[str, np.ndarray] = {}
    for name in args.explain:
        data = full_data(name, store)
        if data is None:
            try:
                database = read_any(name)
            except DatabaseReadError:
                print(f'ERROR: {name} is neither an extraction in the store nor a readable file')
                return 1
            data = next((x.data for pair in database.collision_pairs.values() for x in pair.cross_sections), None)
            if data is None:
                print(f'ERROR: {name} contains no cross-section')
                return 1
        candidates[name] = data
    selected = [
        (pair, xsec)
        for pair in sources[0].database.collision_pairs.values()
        if not args.pair or canonical_pair(pair.name) == canonical_pair(args.pair)
        for xsec in pair.cross_sections
        if not args.key or args.key in xsec.key
    ]
    if len(selected) != 1:
        print(f'ERROR: --explain needs exactly one dataset (--pair and --key), found {len(selected)}')
        return 1
    pair, xsec = selected[0]
    origins = explain(xsec.data, candidates)
    parts: list[Part] = []
    rows = xsec.data.tolist()
    for (energy, _), origin in zip(rows, origins, strict=True):
        if origin is None:
            continue
        if parts and parts[-1].source == origin:
            parts[-1].high = float(energy)
        else:
            parts.append(Part(origin, float(energy), float(energy), candidates[origin]))
    name = f'{pair.name}/' + (f'{xsec.group}/' if xsec.group else '') + xsec.key
    print(f'{name} ({sources[0].label}): {len(xsec.data)} points')
    for part in parts:
        count = sum(1 for (energy, _), origin in zip(rows, origins, strict=True) if origin == part.source and part.low <= energy <= part.high)
        print(f'  {part.low:g}-{part.high:g} eV  {count:4d} points  {part.source}')
    unexplained = [(float(e), float(s)) for (e, s), origin in zip(rows, origins, strict=True) if origin is None]
    if unexplained:
        print(f'  not from these sources: {len(unexplained)} point(s): ' + ', '.join(f'{e:g} eV (σ = {s:g})' for e, s in unexplained[:5]) + (' ...' if len(unexplained) > 5 else ''))
    if parts:
        print('Recipe entry with these parts:\n  - parts:')
        for part in parts:
            print(f'      - {{source: {part.source}, range: [{part.low:g}, {part.high:g}]}}')
        zeros = [e for e, s in unexplained if not abs(s) > 0.0]
        if zeros:
            print(f'    zero_at: {zeros[0]:g}')
    shown = CrossSection(kind=xsec.kind, key=xsec.key, data=xsec.data, group=xsec.group, provenance=xsec.provenance)
    shown.provenance.extra = {**shown.provenance.extra, **({'* Zero at': f'{unexplained[0][0]:g} eV'} if unexplained and not abs(unexplained[0][1]) > 0.0 else {})}
    figure = plot_parts_with(shown, parts, f'{name} ({sources[0].label}): points by source')
    output = pathlib.Path(args.output)
    figure.savefig(output, dpi=150)
    print(f'Plot written to {output}')
    return 0


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

    if args.parts and not args.list:
        return plot_combined(args, sources)
    if args.explain and not args.list:
        return plot_explained(args, sources)
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
