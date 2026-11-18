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

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db import config
from piclas_db.resolve import Origin, Requirement, resolve
from piclas_db.sources import atct
from piclas_db.sources.identify import atct_dataset
from piclas_db.store import Store
# ==================================================================================================================================


def run(args: argparse.Namespace) -> int:
    """ATcT (Active Thermochemical Tables): find the ATcT ID of a species, download species records into the store"""
    try:
        if args.action == 'search':
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
        for resolution in resolve(store, requirements, update=True):
            if resolution.entry is None:
                failed += 1
                continue
            record = atct.parse_atct(resolution.entry.path.read_text(encoding='utf-8'))[0]
            state = 'downloaded' if resolution.origin is Origin.AUTOMATIC else 'in the store'
            print(f'  {state:12s} {record.atct_id:20s} {record.formula:24s} TN {record.version}  -> {resolution.entry.relative}')
        return 1 if failed else 0
    except (atct.ATcTError, config.ConfigError) as e:
        print(f'ERROR: {e}')
        return 1
