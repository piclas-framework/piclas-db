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
import csv
import pathlib
import shutil

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import pytest
import yaml

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db import rates
from piclas_db.common import table
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


def test_build_reactions_from_rate_tables(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """recipe reactions: from a rate table (third body by row), with own Arrhenius parameters, QK; then derived back (rebuild)"""
    from piclas_db.readers import read_database  # noqa: PLC0415

    monkeypatch.setenv('PICLAS_DB_STORE', str(tmp_path / 'store'))
    (tmp_path / 'paper.pdf').write_bytes(PDF)
    assert main(['import', str(tmp_path / 'paper.pdf'), '--literature', 'test-2008', '--doi', '10.0000/test', '--reference', 'A. Author, J. Test 1, 1 (2008)']) == 0
    assert main(['literature', 'template', 'test-2008', 'rates', '--page', '3', '--table', '2', '--rates', '-o', str(tmp_path / 'work')]) == 0
    record_file = tmp_path / 'work' / 'rates.extraction.yaml'
    record = yaml.safe_load(record_file.read_text())
    record['quantity']['assignment']['chemistry_model'] = 'Test2008'
    record['created']['by'] = 'tester'
    record_file.write_text(yaml.safe_dump(record))
    (tmp_path / 'work' / 'rates.csv').write_text((tmp_path / 'work' / 'rates.csv').read_text() + ROWS)
    assert main(['literature', 'add', str(record_file)]) == 0
    recipe = {
        'chemistry_models': {'Set_7Spec_3Reac_Test2008': 'A. Author, J. Test 1, 1 (2008)'},
        'reactions': {
            'Tx2+M_Tx+M+Tx#1': {'reaction': 'Tx2 + M -> Tx + Tx + M', 'rates': 'literature/test-2008/rates', 'row': '1', 'third_body': 'molecules', 'models': {'Set_7Spec_3Reac_Test2008': 'Tx2,TxQq'}},
            'Tx2+Qq_TxQq+Tx#1': {'reactants': ['Tx2', 'Qq'], 'products': ['TxQq', 'Tx'], 'rates': 'literature/test-2008/rates', 'models': {'Set_7Spec_3Reac_Test2008': None}},
            'Qq+electron_QqIon1+electron+electron#1': {
                'reaction': 'Qq + e- -> Qq+ + e- + e-',
                'arrhenius': {'C': 1.0e-14, 'n': 0.0, 'Td': 1.0e5},
                'reference': 'own estimate',
                'models': {'Set_7Spec_3Reac_Test2008': None},
            },
            'Tx+electron_TxIon1+electron+electron#1': {'reaction': 'Tx + e- -> Tx+ + e- + e-', 'model': 'QK', 'models': {'Set_7Spec_3Reac_Test2008': None}},
        },
    }
    (tmp_path / 'recipe.yaml').write_text(yaml.safe_dump(recipe))
    assert main(['build', str(tmp_path / 'recipe.yaml'), '-o', str(tmp_path / 'out.h5')]) == 1  # the table is not reviewed
    assert 'rate table is pending' in capsys.readouterr().out
    assert main(['build', str(tmp_path / 'recipe.yaml'), '-o', str(tmp_path / 'out.h5'), '--allow-unreviewed']) == 0
    db = read_database(tmp_path / 'out.h5')
    dissociation = db.reactions['Tx2+M_Tx+M+Tx#1']
    assert dissociation.attributes['Arrhenius-Prefactor'] == pytest.approx(7.0e21 * TO_SI)
    assert dissociation.attributes['Reactants'] == ['Tx2'] and dissociation.attributes['ChemistryModel'] == [['Set_7Spec_3Reac_Test2008', 'Tx2,TxQq']]
    assert 'row 1 (molecules)' in str(dissociation.provenance.reference)
    assert db.reactions['Tx2+Qq_TxQq+Tx#1'].attributes['Activation-Energy_K'] == pytest.approx(38000.0)
    assert db.reactions['Qq+electron_QqIon1+electron+electron#1'].provenance.reference == 'own estimate'
    assert 'Arrhenius-Prefactor' not in db.reactions['Tx+electron_TxIon1+electron+electron#1'].attributes
    assert db.attributes['Reactions@AvailableChemistryModels,Reference'] == [['Set_7Spec_3Reac_Test2008', 'A. Author, J. Test 1, 1 (2008)']]

    capsys.readouterr()
    # dry run of the same record: checked and shown row by row, compared with the database just built, nothing stored
    assert main(['literature', 'add', '-n', str(record_file), '--compare', str(tmp_path / 'out.h5')]) == 0
    out = capsys.readouterr().out
    assert 'valid: literature/test-2008/rates (p. 3, table 2): 7 rows' in out and '(dry run, nothing stored)' in out
    assert '= Tx2+M_Tx+M+Tx#1' in out and '≠ Tx2+Qq_TxQq+Tx#1' not in out and 'T_d' in out
    assert 'Legend:' in out and 'a value that differs' in out and 'Tx is not compared' in out
    assert 'row(s) with the same values' in out and len(rates.stored_tables(Store(tmp_path / 'store'))) == 1
    assert main(['literature', 'add', '-n', str(record_file), '--compare', str(tmp_path / 'out.h5'), '--color', 'always']) == 0
    out = capsys.readouterr().out
    assert '\x1b[32m= Tx2+M_Tx+M+Tx#1' in out  # same values green (other values: the whole row red; no such reaction gray)
    assert '\x1b[2m' not in out  # the faint attribute is not used (not shown by every terminal)
    other = tmp_path / 'other'  # one value changed: that row is red as a whole, from its first cell on
    shutil.copytree(record_file.parent, other)
    data = other / str(yaml.safe_load(record_file.read_text())['data'])
    rows = list(csv.DictReader(line for line in data.read_text().splitlines() if not line.startswith('#')))
    rows[0]['C'] = '9.9e9'
    with data.open('w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    cells = [rows[0]['row']]
    assert main(['literature', 'add', '-n', str(other / record_file.name), '--compare', str(tmp_path / 'out.h5'), '--color', 'always']) == 0
    out = capsys.readouterr().out
    line = next(line for line in out.splitlines() if '\x1b[31m≠ ' in line)
    assert f'\x1b[33m{cells[0]}' in line and '\x1b[31m≠ ' in line  # the row's name yellow, the comparison red
    assert line.count('\x1b[31m') == 2 and line.count('\x1b[32m') == 2  # red: the changed C and the comparison; green: n and T_d
    table.COLOR_MODE['mode'] = 'auto'
    specs, models, notes = rates.specs_from_database(db, rates.stored_tables(Store(tmp_path / 'store')))
    assert (specs['Tx2+M_Tx+M+Tx#1'].rates is not None, specs['Tx2+M_Tx+M+Tx#1'].row, specs['Tx2+M_Tx+M+Tx#1'].third_body) == (True, '1', 'molecules')
    assert specs['Qq+electron_QqIon1+electron+electron#1'].arrhenius == {'C': 1.0e-14, 'n': 0.0, 'Td': 1.0e5}
    assert specs['Tx+electron_TxIon1+electron+electron#1'].model == 'QK' and models == {'Set_7Spec_3Reac_Test2008': 'A. Author, J. Test 1, 1 (2008)'} and not notes
    again = rates.parse_reaction_spec('Tx2+M_Tx+M+Tx#1', rates.spec_yaml(specs['Tx2+M_Tx+M+Tx#1']))
    assert again == specs['Tx2+M_Tx+M+Tx#1']
    with pytest.raises(rates.RateError, match='either "rates"'):
        rates.parse_reaction_spec('X', {'reaction': 'Tx + Qq -> TxQq', 'models': {'M1': None}})


def test_compare_readings(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    """literature compare: two readings of one table (double entry); grouped third bodies count per species"""
    header = 'row,reaction,third_body,C,n,Td,Tx\n'
    first = header + '1,Tx2 + M -> Tx + Tx + M,"Tx, Qq",3.0^22,-1.6,113200,Ta\n1,Tx2 + M -> Tx + Tx + M,Tx2,7.0^21,-1.6,113200,Ta\n2,Tx + Qq -> TxQq+ + e-,,5.3^12,0,31900,T\n'
    second = header + '1,Tx2 + M -> Tx + Tx + M,Tx,3.0e22,-1.6,113200,Ta\n1,Tx2 + M -> Tx + Tx + M,Qq,3.0e22,-1.6,113200,Ta\n1,Tx2 + M -> Tx + Tx + M,Tx2,7.0e21,-1.6,113200,Ta\n'
    (tmp_path / 'a.csv').write_text(first)
    (tmp_path / 'b.csv').write_text(second)
    (tmp_path / 'c.csv').write_text(second.replace('7.0e21', '7.0e22') + '2,Tx + Qq -> TxQq+ + e-,,5.3^12,0,31900,T\n')
    (tmp_path / 'd.csv').write_text(first)
    assert main(['literature', 'compare', str(tmp_path / 'a.csv'), str(tmp_path / 'd.csv')]) == 0
    assert '4 row(s) agree, 0 difference(s) (the two readings agree)' in capsys.readouterr().out
    assert main(['literature', 'compare', str(tmp_path / 'a.csv'), str(tmp_path / 'b.csv')]) == 1
    out = capsys.readouterr().out
    assert '3 row(s) agree, 1 difference(s)' in out and 'only in the first:  Tx + Qq -> TxQq+ + e- (row 2)' in out
    assert main(['literature', 'compare', str(tmp_path / 'a.csv'), str(tmp_path / 'c.csv')]) == 1
    assert 'differs:            Tx2 + M -> Tx + Tx + M [Tx2]: C 7e+21 vs. 7e+22' in capsys.readouterr().out  # the exponent read differently
