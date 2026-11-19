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


# ----------------------------------------------------------------------------------------------------------------------------------
# ATcT IDs for the species of a database (atct map)
# ----------------------------------------------------------------------------------------------------------------------------------
R = atct.GAS_CONSTANT  # kJ/(mol K)
MAP_RECORDS = [
    record('111-11-1*0', 'Tx  (g)', '-110.000', 28.0),
    record('111-11-1*1', 'Tx  (g, triplet)', '470.', '28.00000'),
    record('222-22-2*0', 'Tx+  (g)', '1500.000', '27.99945', charge=1),
    record('333-33-3*1000', 'Tx  (aq, undissoc)', '-110.000', 28.0),
    record('444-44-4*0', 'TxQ2  (g)', '50.000', 60.0),
    record('444-44-5*0', 'QTxQ  (g)', '50.400', 60.0),  # isomer, nearly the same heat of formation
    record('555-55-5*0', '[Tx]+3  (g)', '9000.000', 27.9984, charge=3),
]


def map_database(path: pathlib.Path) -> pathlib.Path:
    import h5py  # noqa: PLC0415

    values = {'Tx': -110.3 / R, 'TxIon1': 1500.2 / R, 'TxQ2': 50.2 / R, 'TxIon3': 9100.0 / R, 'Zq': 1.0, 'TxIon2': 3000.0 / R}
    with h5py.File(path, 'w') as h5:
        for name, heat in values.items():
            group = h5.create_group(f'Species/{name}')
            group.attrs['HeatOfFormation_K'] = heat
            group.attrs['MassIC'] = 28.0 * atct.ATOMIC_MASS_UNIT * (1 + 1.0e-5)
            group.attrs['* Reference'] = 'HeatOfFormation: Book' if name == 'Zq' else 'HeatOfFormation: ATcT 9.9'
    return path


def test_atct_map_parsing() -> None:
    from piclas_db import atct_map  # noqa: PLC0415

    assert atct_map.piclas_name('ArIon1') == ('Ar', {'Ar': 1}, 1) and atct_map.piclas_name('CO2') == ('CO2', {'C': 1, 'O': 2}, 0)
    assert atct_map.piclas_name('electron') is None
    assert atct_map.atct_formula('[ArH]+ (g)') == ({'Ar': 1, 'H': 1}, 1) and atct_map.atct_formula('OH- (g)') == ({'O': 1, 'H': 1}, -1)
    assert atct_map.atct_formula('HC(O)OH (g)') == ({'H': 2, 'C': 1, 'O': 2}, 0) and atct_map.atct_formula('[C]+6 (g)') == ({'C': 1}, 6)
    assert atct_map.queries('Ar', {'Ar': 1}, 1) == ['Ar+', '[Ar]+', 'Ar', 'argon cation'] and atct_map.queries('C', {'C': 1}, 6) == ['[C]+6', 'C']
    assert atct_map.queries('CO2', {'C': 1, 'O': 2}, 0) == ['CO2', 'carbon dioxide']
    assert atct_map.queries('CN', {'C': 1, 'N': 1}, 1)[:2] == ['[CN]+', 'CN+']


def test_atct_map(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from piclas_db import atct_map  # noqa: PLC0415

    searched: list[str] = []

    def search(term: str) -> list[atct.ATcTSpecies]:
        searched.append(term)
        return [atct.species_from(item) for item in MAP_RECORDS]

    database = read_database(map_database(tmp_path / 'old.h5'))
    assert atct_map.atct_species(database) == ['Tx', 'TxIon1', 'TxIon2', 'TxIon3', 'TxQ2']
    mappings = {mapping.species: mapping for mapping in atct_map.map_species(database, atct_map.atct_species(database), search)}
    assert mappings['Tx'].status is atct_map.Status.MATCH and chosen_id(mappings['Tx']) == '111-11-1*0'
    assert [candidate.record.atct_id for candidate in mappings['Tx'].candidates] == ['111-11-1*0', '111-11-1*1']  # not the aqueous record
    assert mappings['Tx'].candidates[0].mass_deviation == pytest.approx(1.0e-5)
    assert chosen_id(mappings['TxIon1']) == '222-22-2*0'
    assert mappings['TxQ2'].status is atct_map.Status.CHECK  # two isomers within the tolerance
    assert mappings['TxIon3'].status is atct_map.Status.CHECK and mappings['TxIon2'].status is atct_map.Status.NOT_FOUND
    assert searched.count('Tx') == 1  # cached
    recipe = atct_map.recipe_text(list(mappings.values()), 'old.h5', 'own/piclas-parameters')
    assert '  Tx: {atct: 111-11-1*0}  # 111-11-1*0 Tx (g) TN 9.999, dfH +0.300 kJ/mol vs. file' in recipe
    assert '  # TxQ2: check' in recipe and '  #   candidate 444-44-4*0' in recipe

    monkeypatch.setattr(atct, 'search', search)
    out = tmp_path / 'recipe.yaml'
    assert main(['atct', 'map', str(tmp_path / 'old.h5'), '--recipe-out', str(out), '--species', 'Tx', 'TxIon1']) == 0
    assert '2 match' in capsys.readouterr().out
    assert set(load_species(out)) == {'Tx', 'TxIon1'}
    assert main(['atct', 'map', str(tmp_path / 'old.h5')]) == 2  # not everything matched
    assert main(['atct', 'map', str(tmp_path / 'old.h5'), '--species', 'Nope']) == 1


def chosen_id(mapping: object) -> str | None:
    chosen = getattr(mapping, 'chosen', None)
    return None if chosen is None else chosen.record.atct_id


def load_species(path: pathlib.Path) -> dict:
    import yaml  # noqa: PLC0415

    return yaml.safe_load(path.read_text())['species']


def test_atct_map_get(tmp_path: pathlib.Path, api: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    """--get downloads the records of the matched species into the store"""
    store = tmp_path / 'store'
    assert main(['atct', 'map', str(map_database(tmp_path / 'old.h5')), '--species', 'Tx', 'TxIon1', '--get', '--store', str(store)]) == 0
    assert '2 of 2 record(s) in the store' in capsys.readouterr().out
    assert sorted(entry.relative.split('/')[1] for entry in Store(store).entries()) == sorted([atct_dataset('111-11-1*0'), atct_dataset('222-22-2*0')])
    assert any(call.startswith('species/search') for call in api)


def test_atct_map_states_of_one_species() -> None:
    """The ground state named twice ('*0' and '*1 triplet') or ortho/para/normal: the '*0' record; isomers stay to be checked"""
    from piclas_db import atct_map  # noqa: PLC0415

    def candidate(atct_id: str, deviation: float) -> atct_map.Candidate:
        return atct_map.Candidate(atct.species_from(record(atct_id, 'Tx  (g)', '1.0', 28.0)), deviation, None)

    status, ordered = atct_map.decide([candidate('9-9-9*2', -0.006), candidate('9-9-9*0', -0.007), candidate('9-9-9*1', -0.008), candidate('9-9-9*3', 72.0)], 1.0)
    assert status is atct_map.Status.MATCH and ordered[0].record.atct_id == '9-9-9*0' and len(ordered) == 4
    status, _ = atct_map.decide([candidate('9-9-9*0', 0.01), candidate('8-8-8*0', 0.02)], 1.0)
    assert status is atct_map.Status.CHECK
    status, _ = atct_map.decide([candidate('9-9-9*1', 0.01), candidate('9-9-9*2', 0.02)], 1.0)
    assert status is atct_map.Status.CHECK  # no '*0' record


def test_search_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    """All pages of a search, until 'total' is reached; at most 'pages' requests"""
    items = [record(f'1-1-{number}*0', 'Tx  (g)', '1.0', 28.0) for number in range(120)]
    offsets: list[str] = []

    def request(path: str, parameters: dict[str, str], timeout: float = 60.0, retries: int = 3) -> str:
        offsets.append(parameters['offset'])
        start = int(parameters['offset'])
        return json.dumps({'items': items[start : start + int(parameters['limit'])], 'total': len(items), 'limit': 50, 'offset': start})

    monkeypatch.setattr(atct, 'request', request)
    monkeypatch.setattr(atct, 'PAUSE', 0.0)
    assert len(atct.search('Tx')) == 120 and offsets == ['0', '50', '100']
    offsets.clear()
    assert len(atct.search('Tx', pages=1)) == 50 and offsets == ['0']
