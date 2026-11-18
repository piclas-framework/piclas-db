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
"""Active Thermochemical Tables (ATcT, Argonne National Laboratory): API responses and their values

The ATcT API (https://atct.anl.gov/api/v1/) returns species as JSON: TN version, ATcT ID (e.g. '630-08-0*0', the suffix numbers the
phase/state; '*0' is usually the gas-phase ground state), enthalpies of formation at 0 K and 298.15 K in kJ/mol, molar mass in u,
charge. Ions follow the stationary-electron (ion) convention, as PICLas databases do. Every response is stored unchanged in the store
(provider 'atct', dataset = ATcT ID), so that the values can always be traced to the downloaded record and its TN version.

Values are strings with trailing dots ('25.'), numbers, 'exact' or null; this module turns them into floats or None.
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional
# ==================================================================================================================================

API = 'https://atct.anl.gov/api/v1'
GAS_CONSTANT = 8.314462618e-3  # kJ/(mol K)
ATOMIC_MASS_UNIT = 1.66053906892e-27  # kg
PAUSE = 1.0  # s between requests: the API is a public service


class ATcTError(Exception):
    """ATcT response cannot be read or the service is not reachable"""


@dataclass
class ATcTSpecies:
    version: str  # ATcT thermochemical network version, e.g. '1.228'
    atct_id: str
    name: str
    formula: str  # as given, e.g. 'CO  (g)', '[Ar]+2  (g)'
    hf_0k: Optional[float]  # kJ/mol
    hf_298k: Optional[float]  # kJ/mol
    hf_298k_uncertainty: Optional[float]  # kJ/mol (0 for 'exact')
    mass: Optional[float]  # u
    mass_uncertainty: Optional[float]
    charge: int
    raw: dict[str, Any]

    @property
    def gas(self) -> bool:
        return '(g' in self.formula

    @property
    def heat_of_formation_k(self) -> Optional[float]:
        """HeatOfFormation_K as in PICLas databases: enthalpy of formation at 298.15 K divided by R"""
        return None if self.hf_298k is None else self.hf_298k / GAS_CONSTANT

    @property
    def mass_kg(self) -> Optional[float]:
        return None if self.mass is None else self.mass * ATOMIC_MASS_UNIT


def number(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text.lower() == 'exact':
        return 0.0
    try:
        return float(text)
    except ValueError:
        return None


def field(item: dict[str, Any], name: str) -> Any:
    """Field by name; the API writes the increment sign as '∆' (U+2206), also accepted as 'Δ' (U+0394) or 'dfH'"""
    for key in (name, name.replace('∆', 'Δ'), name.replace('∆f', 'df')):
        if key in item:
            return item[key]
    return None


def species_from(item: dict[str, Any]) -> ATcTSpecies:
    if not isinstance(item, dict) or 'ATcT_ID' not in item:
        raise ATcTError('not an ATcT species record (no ATcT_ID)')
    return ATcTSpecies(
        version=str(item.get('ATcT_TN_Version', '')),
        atct_id=str(item['ATcT_ID']),
        name=str(item.get('Name', '')),
        formula=' '.join(str(item.get('Formula', '')).split()),
        hf_0k=number(field(item, '∆fH_0K')),
        hf_298k=number(field(item, '∆fH_298K')),
        hf_298k_uncertainty=number(field(item, '∆fH_298K_uncertainty')),
        mass=number(item.get('mass')),
        mass_uncertainty=number(item.get('mass_uncertainty')),
        charge=int(item.get('charge') or 0),
        raw=item,
    )


def is_atct(text: str) -> bool:
    return '"ATcT_ID"' in text[:5000] or '"ATcT_TN_Version"' in text[:5000]


def parse_atct(text: str) -> list[ATcTSpecies]:
    """Species of an API response: one record (get/by-atctid) or a list ({"items": [...]}, search and get/by-formula)"""
    try:
        content = json.loads(text)
    except json.JSONDecodeError as e:
        raise ATcTError(f'not JSON: {e}') from e
    items = content.get('items') if isinstance(content, dict) and 'items' in content else [content]
    return [species_from(item) for item in items or []]


# ----------------------------------------------------------------------------------------------------------------------------------
# API
# ----------------------------------------------------------------------------------------------------------------------------------
def request(path: str, parameters: dict[str, str], timeout: float = 60.0, retries: int = 3) -> str:
    """GET <API>/<path>/?<parameters> (trailing slash, redirects followed by urllib), with retries; returns the response text"""
    from piclas_db.common.common_vars import Common  # noqa: PLC0415

    url = f'{API}/{path.strip("/")}/?{urllib.parse.urlencode(parameters)}'
    headers = {'User-Agent': f'piclas-db/{Common().version} (https://github.com/piclas-framework/piclas-db)', 'Accept': 'application/json'}
    last: Optional[Exception] = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as response:  # noqa: S310 (fixed https host)
                return response.read().decode('utf-8')
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            time.sleep(PAUSE * (attempt + 1))
    raise ATcTError(f'ATcT API not reachable ({url}): {last}')


def get(atct_id: str) -> str:
    """Response text for one species (stored unchanged as the original file)"""
    time.sleep(PAUSE)
    return request('species/get/by-atctid', {'atctid': atct_id})


def search(query: str) -> list[ATcTSpecies]:
    time.sleep(PAUSE)
    return parse_atct(request('species/search', {'q': query, 'limit': '50'}))
