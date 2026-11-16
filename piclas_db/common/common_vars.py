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
import importlib.metadata
import os
import pathlib
import re
import subprocess
from collections.abc import Callable
from typing import Final, Optional, Self

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
from packaging.version import Version
# ==================================================================================================================================

PROGRAM: Final[str] = 'piclas-db'  # name of the command-line tool and of the package on PyPI


# PEP 318 – Decorators for Functions and Methods
# > https://peps.python.org/pep-0318/
def singleton(cls: Callable) -> Callable:
    instances = {}

    def getinstance() -> Callable:
        if cls not in instances:
            instances[cls] = cls()
        return instances[cls]

    return getinstance


@singleton
class Common:
    """Program name, version and git commit, determined once and shared by all modules"""

    def __init__(self: Self) -> None:
        self._program: Final[str] = PROGRAM
        self._version: Final[Version] = self.__version__
        self._commit: Final[Optional[str]] = self.__commit__

    @property
    def __version__(self) -> Version:
        # Retrieve version from package metadata
        try:
            version = importlib.metadata.version(PROGRAM)
        # Fallback to pyproject.toml (e.g. when running from a source checkout without installation)
        except importlib.metadata.PackageNotFoundError as e:
            pyproject = pathlib.Path(__file__).parent.parent.parent / 'pyproject.toml'
            if not pyproject.exists():
                raise FileNotFoundError(f'pyproject.toml not found at {pyproject}') from e

            with pyproject.open('r') as p:
                match = re.search(r'^version\s*=\s*["\'](.+?)["\']', p.read(), flags=re.MULTILINE)
            if not match:
                raise ValueError('Version not found in pyproject.toml') from e
            version = match.group(1)

        return Version(version)

    @property
    def __commit__(self) -> Optional[str]:
        # Retrieve commit from git (only available when running from a git checkout)
        try:
            process = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=os.path.dirname(os.path.realpath(__file__)), capture_output=True, check=False)
        # Return if git is not available
        except FileNotFoundError:
            return None

        if process.returncode != 0:
            return None
        return process.stdout.strip().decode('ascii')

    @property
    def program(self) -> str:
        return str(self._program)

    @property
    def version(self) -> str:
        return str(self._version)

    @property
    def commit(self) -> Optional[str]:
        return self._commit

    def version_string(self) -> str:
        return f'{self.program} {self.version}' + (f' [commit {self.commit}]' if self.commit else '')
