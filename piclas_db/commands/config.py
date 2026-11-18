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
import os

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db import config
from piclas_db.store import default_store
# ==================================================================================================================================


def run(args: argparse.Namespace) -> int:
    """Show the configuration file and the settings in effect, or create a commented template (--init)"""
    path = config.config_path()
    if args.init:
        if path.exists():
            print(f'ERROR: {path} exists already')
            return 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(config.TEMPLATE)
        print(f'Template written: {path} (remove the # of the lines you want to use)')
        return 0
    try:
        content = config.load()
    except config.ConfigError as e:
        print(f'ERROR: {e}')
        return 1
    print(f'Configuration file: {path}' + ('' if path.is_file() else ' (not present; piclas-db config --init writes a template)'))
    store_source = 'environment ($PICLAS_DB_STORE)' if os.environ.get('PICLAS_DB_STORE') else ('configuration' if config.value('store') else 'default')
    print(f'  store:  {default_store()}  [{store_source}]')
    mirror = os.environ.get('PICLAS_DB_MIRROR') or config.value('mirror')
    mirror_source = 'environment ($PICLAS_DB_MIRROR)' if os.environ.get('PICLAS_DB_MIRROR') else 'configuration'
    print(f'  mirror: {mirror}  [{mirror_source}]' if mirror else '  mirror: not set (the remote of the store clone is used, if any)')
    for section, options in content.items():
        if section in config.GLOBAL_KEYS:
            continue
        print(f'  {section}:')
        for option, setting in (options or {}).items() if isinstance(options, dict) else []:
            print(f'    {option}: {setting}')
    return 0
