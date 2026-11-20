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
"""The release workflow checks the tag against pyproject.toml, CHANGELOG.md and CITATION.cff; the same checks here catch a version
bump that missed a file before a tag is pushed (v0.40.0 failed: CITATION.cff still said 0.30.2)"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import pathlib
import re
import tomllib

# ==================================================================================================================================
ROOT = pathlib.Path(__file__).resolve().parents[1]


def project_version() -> str:
    return tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version']


def test_citation_versions_match_pyproject() -> None:
    versions = re.findall(r'^\s*version: "([^"]+)"$', (ROOT / 'CITATION.cff').read_text(encoding='utf-8'), flags=re.MULTILINE)
    assert versions and set(versions) == {project_version()}, f'CITATION.cff versions {versions}, pyproject.toml {project_version()}'


def test_changelog_has_section_for_version() -> None:
    assert re.search(rf'^## {re.escape(project_version())}$', (ROOT / 'CHANGELOG.md').read_text(encoding='utf-8'), flags=re.MULTILINE)
