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
import json
import pathlib

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import pytest

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.piclas_db import main
from piclas_db.readers import read_database
from piclas_db.sources import atct
from piclas_db.sources.identify import IdentifyError, atct_dataset, atct_id_of, identify
from piclas_db.store import Store
# ==================================================================================================================================
# Records in the structure of the ATcT API (v1); the values are invented


def record(atct_id: str, formula: str, hf298: object, mass: object, charge: int = 0, name: str = 'Testium') -> dict:
    return {
        'ATcT_TN_Version': '9.999',
        'ATcT_ID': atct_id,
        'Name': name,
        'Formula': formula,
        '∆fH_0K': '-100.000',
        '∆fH_298K': hf298,
        '∆fH_298K_uncertainty': 'exact' if hf298 == '0' else '0.025',
        'units': 'kJ/mol',
        'mass': mass,
        'mass_uncertainty': '0.00085',
        'charge': charge,
    }


SPECIES = {
    '111-11-1*0': record('111-11-1*0', 'Tx  (g)', '-110.000', 28.0, name='Testium monoxide'),
    '111-11-1*1': record('111-11-1*1', 'Tx  (g, triplet)', '470.', '28.00000'),
    '222-22-2*0': record('222-22-2*0', 'Tx+  (g)', '1500.000', '27.99945', charge=1, name='Testium cation'),
    '333-33-3*1000': record('333-33-3*1000', 'Tx  (aq, undissoc)', None, 28.0),
}


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The ATcT API answered from SPECIES; the list records the requests"""
    calls: list[str] = []

    def request(path: str, parameters: dict[str, str], timeout: float = 60.0, retries: int = 3) -> str:
        calls.append(f'{path} {parameters}')
        if path == 'species/get/by-atctid':
            if parameters['atctid'] not in SPECIES:
                raise atct.ATcTError('not found')
            return json.dumps(SPECIES[parameters['atctid']], ensure_ascii=False)
        items = list(SPECIES.values())
        return json.dumps({'items': items, 'total': len(items), 'limit': 50, 'offset': 0}, ensure_ascii=False)

    monkeypatch.setattr(atct, 'request', request)
    monkeypatch.setattr(atct, 'PAUSE', 0.0)
    return calls


def test_parse() -> None:
    species = atct.parse_atct(json.dumps({'items': list(SPECIES.values())}, ensure_ascii=False))
    assert [s.atct_id for s in species] == list(SPECIES)
    first, triplet, ion, aqueous = species
    assert first.hf_298k == pytest.approx(-110.0) and first.heat_of_formation_k == pytest.approx(-110.0 / 8.314462618e-3)
    assert first.mass_kg == pytest.approx(28.0 * 1.66053906892e-27) and first.gas and first.formula == 'Tx (g)'
    assert triplet.hf_298k == pytest.approx(470.0) and triplet.mass == pytest.approx(28.0)  # '470.' and mass as string
    assert ion.charge == 1 and not aqueous.gas and aqueous.hf_298k is None and aqueous.heat_of_formation_k is None
    zero = atct.species_from(record('1*0', 'Ar  (g)', '0', 39.948))
    assert zero.hf_298k_uncertainty == pytest.approx(0.0)  # 'exact'
    assert atct.number('x') is None
    assert atct.parse_atct('{"items": [], "total": 0}') == []
    with pytest.raises(atct.ATcTError):
        atct.parse_atct('<html>')
    with pytest.raises(atct.ATcTError):
        atct.species_from({'Name': 'no id'})
    assert atct_dataset('630-08-0*0') == '630-08-0-0' and atct_id_of('630-08-0-0') == '630-08-0*0'


def test_identify(tmp_path: pathlib.Path) -> None:
    one = tmp_path / 'one.json'
    one.write_text(json.dumps(SPECIES['111-11-1*0'], ensure_ascii=False))
    identified = identify(one)
    assert (identified.provider, identified.kind, identified.dataset) == ('atct', 'species', '111-11-1-0')
    assert identified.details['version'] == '9.999'
    many = tmp_path / 'many.json'
    many.write_text(json.dumps({'items': list(SPECIES.values())}, ensure_ascii=False))
    with pytest.raises(IdentifyError, match='one species per file'):
        identify(many)


def test_search_and_get(api: list[str], tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = tmp_path / 'store'
    assert main(['atct', 'search', 'testium']) == 0
    out = capsys.readouterr().out
    assert '111-11-1*0' in out and '222-22-2*0' in out and '333-33-3*1000' not in out  # gas phase only
    assert main(['atct', 'search', 'testium', '--all']) == 0
    assert '333-33-3*1000' in capsys.readouterr().out

    assert main(['atct', 'get', '111-11-1*0', '222-22-2*0', '--store', str(store)]) == 0
    out = capsys.readouterr().out
    assert out.count('downloaded') == 2 and 'downloading atct/111-11-1-0 from ATcT done (' in out  # progress with elapsed time
    assert '2 of 2 record(s) in the store (' in out
    entries = Store(store).entries()
    assert {entry.meta['dataset'] for entry in entries} == {'111-11-1-0', '222-22-2-0'}
    assert entries[0].meta['imported_by'] == 'piclas-db test <test@example.com>'
    assert main(['atct', 'get', '111-11-1*0', '--store', str(store)]) == 0  # already there: no new request
    assert 'in the store' in capsys.readouterr().out
    assert sum('by-atctid' in call for call in api) == 2
    assert main(['atct', 'get', '999-99-9*0', '--store', str(store)]) == 1  # unknown ID
    assert 'automatic download of atct/999-99-9-0 failed' in capsys.readouterr().out


def test_build_with_atct(api: list[str], tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    store = tmp_path / 'store'
    recipe = tmp_path / 'recipe.yaml'
    recipe.write_text(
        'species:\n'
        '  TxO: {atct: 111-11-1*0, InteractionID: 2}\n'
        '  TxIon1: {atct: 222-22-2*0, MassIC: 1.0e-26}\n'  # a value in the recipe takes precedence
        '  TxIon2: {atct: 222-22-2*0}\n'  # charge 1, but the name says 2
    )
    output = tmp_path / 'database.h5'
    assert main(['build', str(recipe), '-o', str(output), '--store', str(store), '--offline']) == 1  # offline: no download
    assert main(['build', str(recipe), '-o', str(output), '--store', str(store)]) == 0  # downloaded automatically
    out = capsys.readouterr().out
    assert 'automatic download' in out and 'has charge 1, the name suggests 2' in out
    database = read_database(output)
    oxide, ion = database.species['TxO'], database.species['TxIon1']
    assert oxide.attributes['HeatOfFormation_K'] == pytest.approx(-110.0 / 8.314462618e-3)
    assert oxide.attributes['MassIC'] == pytest.approx(28.0 * 1.66053906892e-27) and oxide.attributes['InteractionID'] == 2
    assert ion.attributes['MassIC'] == pytest.approx(1.0e-26) and ion.attributes['HeatOfFormation_K'] == pytest.approx(1500.0 / 8.314462618e-3)
    assert 'ATcT 9.999 (111-11-1*0, Tx (g)): HeatOfFormation_K, MassIC' in str(oxide.provenance.reference)
    assert 'atct/111-11-1-0' in str(oxide.provenance.extra.get('* Source'))

    # without identity, nothing is downloaded (who added the data is part of the record)
    monkeypatch.delenv('PICLAS_DB_USER_NAME')
    recipe.write_text('species:\n  Tx: {atct: 111-11-1*1}\n')
    assert main(['build', str(recipe), '-o', str(tmp_path / 'other.h5'), '--store', str(store)]) == 1
    assert 'Please tell piclas-db who you are' in capsys.readouterr().out
