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
"""Reaction rate tables (literature template --rates) and their comparison with the reactions of a database (rebuild --explain);
invented species (Tx, Qq) and values, no content of real papers"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import pathlib

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import pytest
import yaml

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db import rates
from piclas_db.model import Database, Reaction
from piclas_db.piclas_db import main
from piclas_db.schema import Schema
from piclas_db.store import Store
# ==================================================================================================================================

PDF = b'%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n'
ROWS = """1,Tx2 + M -> Tx + Tx + M,"Tx, Qq",3.0e22,-1.6,100000,Ta
1,Tx2 + M -> Tx + Tx + M,molecules,7.0e21,-1.6,100000,Ta
1,Tx2 + M -> Tx + Tx + M,e-,1.2^25,-1.6,100000,Ta
2,Tx2 + Qq -> TxQq + Tx,,6.4e17,-1.0,38000,T
3,Tx + Qq -> TxQq+ + e-,,8.8e8,1.0,31000,T
4,Tx + e- -> Tx+ + e- + e-,,3.9e33,-3.78,150000,Te
5,Tx + Tx + M -> Tx2 + M,all,1.0e15,-0.5,,T
"""
TO_SI = 1.0e-6 / rates.AVOGADRO


def test_species_and_reactions() -> None:
    assert [rates.species_name(s) for s in ('N2+', 'C+6', 'CO2+', 'O++', 'e-', 'NO+', 'Ar')] == ['N2Ion1', 'CIon6', 'CO2Ion1', 'OIon2', 'electron', 'NOIon1', 'Ar']
    key, body = rates.canonical(*rates.split_reaction('Tx2 + Ar -> Tx + Tx + Ar'))
    assert (key.reactants, key.products, body) == (('Tx2',), ('Tx', 'Tx'), 'Ar')
    key, body = rates.canonical(*rates.split_reaction('Tx + Qq → TxQq+ + e-'))
    assert (key.products, body) == (('TxQqIon1', 'electron'), None)
    assert rates.parse_number('1.2^25') == pytest.approx(1.2e25) and rates.parse_number('3.0x10^-3') == pytest.approx(3.0e-3)
    rows = rates.read_rate_table('row,reaction,third_body,C,n,Td,Tx\n' + ROWS)
    assert len(rows) == 7 and rows[0].third_bodies == ('Tx', 'Qq') and rows[6].order == 3 and rows[6].Td == pytest.approx(0.0, abs=0)
    assert rows[6].prefactor('cm^3/(mol s)') == pytest.approx(1.0e15 * TO_SI**2)
    with pytest.raises(rates.RateError, match='row 2: Tx'):
        rates.read_rate_table('row,reaction,third_body,C,n,Td,Tx\n1,Tx + Qq -> TxQq,,1,0,0,Tq\n')
    with pytest.raises(rates.RateError, match='columns missing'):
        rates.read_rate_table('row,reaction,C\n1,Tx + Qq -> TxQq,1\n')


def reaction(name: str, reactants: list[str], products: list[str], C: float, n: float, Td: float, models: list) -> Reaction:
    return Reaction(name, {'Reactants': reactants, 'Products': products, 'Arrhenius-Prefactor': C, 'Arrhenius-Powerfactor': n, 'Activation-Energy_K': Td, 'ChemistryModel': models, 'ReactionModel': ['TCE']})


def test_explain_reactions() -> None:
    table = rates.Table('literature/test-2008/rates', 'Test2008', 'cm^3/(mol s)', rates.read_rate_table('row,reaction,third_body,C,n,Td,Tx\n' + ROWS))
    db = Database(path='old.h5', schema=Schema.SPECIES_DATABASE)
    for item in (
        reaction('Tx2+M_Tx+M+Tx#1', ['Tx2'], ['Tx', 'Tx'], 1.16e-8, -1.6, 100000, [['Set_Test2008', 'Tx2,TxQq'], ['Other_Unknown2000', 'Tx2']]),  # molecules: 7.0e21
        reaction('Tx2+A_Tx+A+Tx#1', ['Tx2'], ['Tx', 'Tx'], 4.98e-8, -1.6, 100000, [['Set_Test2008', 'Tx,Qq,TxIon1,Zz']]),  # Zz is no species of the table
        reaction('Tx2+Qq_TxQq+Tx#1', ['Tx2', 'Qq'], ['TxQq', 'Tx'], 1.063e-12, -1.0, 38370, [['Set_Test2008']]),  # T_d differs
        reaction('Tx2+electron_Tx+Tx+electron#1', ['Tx2', 'electron'], ['Tx', 'Tx', 'electron'], 1.993e-5, -1.6, 100000, [['Set_Test2008']]),
        reaction('Tx+Tx_Tx2#1', ['Tx', 'Tx'], ['Tx2'], 1.0e15 * TO_SI**2, -0.5, 0.0, [['Set_Test2008']]),  # no third body in the database
    ):
        db.reactions[item.name] = item
    results = {result.name: result for result in rates.explain_reactions(db, [table])}
    checks = {name: [(c.model, c.status, c.details) for c in result.checks] for name, result in results.items()}
    assert checks['Tx2+M_Tx+M+Tx#1'] == [('Set_Test2008', 'match', []), ('Other_Unknown2000', 'no table', [])]
    assert checks['Tx2+A_Tx+A+Tx#1'][0][1:] == ('missing', ['TxIon1, Zz: not in the table'])  # rows only for Tx, Qq, molecules, e-
    assert checks['Tx2+Qq_TxQq+Tx#1'][0][1:] == ('differs', ['T_d 38370 vs. 38000 (row 2)'])
    assert checks['Tx2+electron_Tx+Tx+electron#1'][0][1] == 'match'
    assert results['Tx2+M_Tx+M+Tx#1'].found_in == ['literature/test-2008/rates row 1 (molecules)']
    assert 'reactions in no table' in rates.summary(list(results.values()))


def test_literature_add_and_rebuild_explain(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv('PICLAS_DB_STORE', str(tmp_path / 'store'))
    (tmp_path / 'paper.pdf').write_bytes(PDF)
    assert main(['import', str(tmp_path / 'paper.pdf'), '--literature', 'Test 2008', '--doi', '10.0000/test', '--reference', 'A. Author, J. Test 1, 1 (2008)']) == 0
    assert main(['literature', 'template', 'test-2008', 'rates', '--page', '3 (11)', '--table', '2', '--rates', '-o', str(tmp_path / 'work')]) == 0
    record_file, data_file = tmp_path / 'work' / 'rates.extraction.yaml', tmp_path / 'work' / 'rates.csv'
    record = yaml.safe_load(record_file.read_text())
    assert record['rate_table'] and record['columns']['rate']['unit'] == 'cm^3/(mol s)'
    record['quantity']['assignment']['chemistry_model'] = 'Test2008'
    record['created']['by'] = 'tester'
    record_file.write_text(yaml.safe_dump(record))
    data_file.write_text(data_file.read_text() + ROWS)
    capsys.readouterr()
    assert main(['literature', 'add', str(record_file)]) == 0
    assert '(7 rows, review pending)' in capsys.readouterr().out
    tables = rates.stored_tables(Store(tmp_path / 'store'))
    assert len(tables) == 1 and tables[0].chemistry_model == 'Test2008' and not tables[0].approved
    data_file.write_text(data_file.read_text() + '9,Tx + Qq -> TxQq,,-1,0,0,T\n')
    record_file.write_text(yaml.safe_dump({**record, 'name': 'rates-bad'}))
    assert main(['literature', 'add', str(record_file)]) == 1
    assert 'C must be positive' in capsys.readouterr().out
