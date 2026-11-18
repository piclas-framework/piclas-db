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
"""Configuration file: defaults for the store, the private repository and command options

    ~/.config/piclas-db/config.yaml   ($XDG_CONFIG_HOME/piclas-db/config.yaml, or the file named by $PICLAS_DB_CONFIG)

    store: ~/data/piclas-db-store
    mirror: git@github.com:piclas-framework/piclas-db-sources.git
    extract:                # defaults for the options of a command (option names as on the command line, '-' or '_')
      by: Stephen Copplestone
    literature:
      reviewer: Stephen Copplestone
    reservoir:
      collision-probability: 0.01

Order: command line, then environment variables ($PICLAS_DB_STORE, $PICLAS_DB_MIRROR), then this file, then the built-in defaults.
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import argparse
import os
import pathlib
from functools import cache
from typing import Any, Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import yaml
# ==================================================================================================================================

GLOBAL_KEYS = ('store', 'mirror')
TEMPLATE = """# piclas-db configuration (see 'piclas-db config --help'); command line and environment variables take precedence
# store: ~/data/piclas-db-store                 # local store of original files
# mirror: git@github.com:<org>/<private-repo>.git   # private source repository
# extract:
#   by: Your Name                              # who extracts data from papers (extraction records)
# literature:
#   reviewer: Your Name                        # default reviewer for 'literature review'
# reservoir:
#   collision-probability: 0.01
#   tolerance: 0.05
"""


class ConfigError(Exception):
    """Configuration file cannot be read"""


def config_path() -> pathlib.Path:
    if os.environ.get('PICLAS_DB_CONFIG'):
        return pathlib.Path(os.environ['PICLAS_DB_CONFIG']).expanduser()
    config_home = os.environ.get('XDG_CONFIG_HOME') or str(pathlib.Path.home() / '.config')
    return pathlib.Path(config_home) / 'piclas-db' / 'config.yaml'


def load() -> dict[str, Any]:
    """Content of the configuration file ({} if there is none)"""
    path = config_path()
    return read(path, path.stat().st_mtime if path.is_file() else 0.0)


@cache
def read(path: pathlib.Path, _modified: float) -> dict[str, Any]:
    """Cached per path and modification time"""
    if not path.is_file():
        return {}
    try:
        content = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    except (OSError, yaml.YAMLError) as e:
        raise ConfigError(f'cannot read the configuration {path}: {e}') from e
    if not isinstance(content, dict):
        raise ConfigError(f'{path}: the configuration is a mapping (key: value)')
    return content


def value(key: str) -> Optional[str]:
    """Global setting ('store', 'mirror') from the configuration file"""
    entry = load().get(key)
    return str(entry) if entry is not None else None


def apply(args: argparse.Namespace, subparser: argparse.ArgumentParser) -> list[str]:
    """Fill options of the command that were not given on the command line from the configuration; returns warnings about unknown
    entries (they are ignored)"""
    content = load()
    known_commands = set(getattr(subparser, '_piclas_db_commands', ()))
    warnings = [f'unknown entry {key!r} in {config_path()}' for key in content if key not in GLOBAL_KEYS and known_commands and key not in known_commands]
    section = content.get(args.command) or {}
    if not isinstance(section, dict):
        return [*warnings, f'{args.command}: the entry in {config_path()} must be a mapping of options']
    for option, setting in section.items():
        dest = str(option).replace('-', '_')
        if not hasattr(args, dest) or dest == 'command':
            warnings.append(f'{args.command}: unknown option {option!r} in {config_path()}')
            continue
        if getattr(args, dest) == subparser.get_default(dest):  # not given on the command line
            setattr(args, dest, setting)
    return warnings
