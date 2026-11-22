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
"""Shared test setup: neither the configuration file of the person running the tests nor the network may influence them"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import pathlib

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import pytest
# ==================================================================================================================================


@pytest.fixture(autouse=True)
def no_user_configuration(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('PICLAS_DB_CONFIG', str(tmp_path / 'no-config.yaml'))
    monkeypatch.delenv('PICLAS_DB_STORE', raising=False)
    monkeypatch.delenv('PICLAS_DB_MIRROR', raising=False)
    monkeypatch.setenv('PICLAS_DB_USER_NAME', 'piclas-db test')
    monkeypatch.setenv('PICLAS_DB_USER_EMAIL', 'test@example.com')


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Crossref is never asked: imports behave as offline (tests of the lookup replace get_json themselves)"""
    from piclas_db.sources import doi  # noqa: PLC0415

    def unreachable(url: str, timeout: float) -> None:
        raise doi.Unreachable('Crossref not reachable: tests run offline')

    monkeypatch.setattr(doi, 'get_json', unreachable)
