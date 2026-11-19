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
import time

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db import config
from piclas_db.common.progress import progress
from piclas_db.git import GitError
from piclas_db.resolve import Origin, Requirement, resolve
from piclas_db.sources import atct
from piclas_db.sources.identify import atct_dataset
from piclas_db.store import Store
# ==================================================================================================================================


def map_ids(args: argparse.Namespace) -> int:
    """ATcT IDs for the species of a database, checked against the heats of formation stored in it"""
    from piclas_db import atct_map  # noqa: PLC0415
    from piclas_db.readers import DatabaseReadError, read_database  # noqa: PLC0415

    if len(args.arguments) != 1:
        print('ERROR: atct map takes one database file')
        return 1
    try:
        database = read_database(args.arguments[0])
    except DatabaseReadError as e:
        print(f'ERROR: {e}')
        return 1
    names = args.species or atct_map.atct_species(database)
    unknown = [name for name in names if name not in database.species]
    if unknown or not names:
        print(f'ERROR: not in {args.arguments[0]}: {", ".join(unknown)}' if unknown else f'ERROR: no species of {args.arguments[0]} credits ATcT (use --species)')
        return 1
    start = time.monotonic()
    with progress(f'searching ATcT for {len(names)} species'):
        mappings = atct_map.map_species(database, names, atct.search, tolerance=args.tolerance)
    for mapping in mappings:
        chosen = mapping.chosen
        print(f'{mapping.species:10s} {mapping.status.value:20s} ' + (atct_map.describe(chosen) if chosen else f'searched: {", ".join(mapping.queries) or "-"}'))
        if chosen is None:
            for candidate in mapping.candidates[:3]:
                print(f'{"":31s}candidate {atct_map.describe(candidate)}')
    counts = {status: sum(mapping.status is status for mapping in mappings) for status in atct_map.Status}
    print(', '.join(f'{count} {status.value}' for status, count in counts.items() if count) + f' ({time.monotonic() - start:.1f} s, tolerance {args.tolerance} kJ/mol)')
    if args.recipe_out:
        pathlib.Path(args.recipe_out).write_text(atct_map.recipe_text(mappings, args.arguments[0], args.own_data or None), encoding='utf-8')
        print(f'Recipe entries: {args.recipe_out}')
    ids = [mapping.chosen.record.atct_id for mapping in mappings if mapping.chosen is not None]
    if args.get and ids:
        config.require_identity()
        failed = sum(resolution.entry is None for resolution in resolve(Store(args.store), [Requirement('atct', atct_dataset(atct_id)) for atct_id in ids], update=True))
        print(f'{len(ids) - failed} of {len(ids)} record(s) in the store')
        if failed:
            return 1
    return 0 if counts[atct_map.Status.MATCH] == len(mappings) else 2


def run(args: argparse.Namespace) -> int:
    """ATcT (Active Thermochemical Tables): find the ATcT ID of a species, download species records into the store"""
    try:
        if args.action == 'map':
            return map_ids(args)
        if args.action == 'search':
            with progress(f'searching ATcT for {" ".join(args.arguments)!r}'):
                found = atct.search(' '.join(args.arguments))
            found = [record for record in found if record.gas or args.all]
            if not found:
                print('No gas-phase species found' + ('' if args.all else ' (--all also shows other phases)'))
                return 1
            print(f'{"ATcT ID":20s} {"formula":24s} {"charge":>6s} {"dfH(298 K) kJ/mol":>18s} {"HeatOfFormation_K":>18s}  name (TN version)')
            for record in found:
                heat = f'{record.heat_of_formation_k:18.2f}' if record.heat_of_formation_k is not None else f'{"-":>18s}'
                value = f'{record.hf_298k:18.3f}' if record.hf_298k is not None else f'{"-":>18s}'
                print(f'{record.atct_id:20s} {record.formula:24s} {record.charge:6d} {value} {heat}  {record.name} ({record.version})')
            print('Use the ID in a recipe: species: {<name>: {atct: <ATcT ID>}}')
            return 0
        config.require_identity()
        store = Store(args.store)
        requirements = [Requirement('atct', atct_dataset(atct_id)) for atct_id in args.arguments]
        failed = 0
        start = time.monotonic()
        for resolution in resolve(store, requirements, update=True):
            if resolution.entry is None:
                failed += 1
                continue
            record = atct.parse_atct(resolution.entry.path.read_text(encoding='utf-8'))[0]
            state = 'downloaded' if resolution.origin is Origin.AUTOMATIC else 'in the store'
            print(f'  {state:12s} {record.atct_id:20s} {record.formula:24s} TN {record.version}  -> {resolution.entry.relative}')
        print(f'{len(requirements) - failed} of {len(requirements)} record(s) in the store ({time.monotonic() - start:.1f} s; ATcT is asked at most once per second)')
        return 1 if failed else 0
    except (atct.ATcTError, config.ConfigError, GitError) as e:
        print(f'ERROR: {e}')
        return 1
