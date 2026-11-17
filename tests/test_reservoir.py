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
import math
import pathlib

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import numpy as np
import pytest
import yaml

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.model import CollisionPair, CrossSection, Database, Species, XSecKind
from piclas_db.piclas_db import main
from piclas_db.plot import ELECTRON_MASS, EV
from piclas_db.reservoir import ReservoirError, Settings, as_used_by_piclas, evaluate, heat_of_reaction, plan
from piclas_db.schema import Schema
from piclas_db.writer import write_database
# ==================================================================================================================================
# Synthetic database (invented numbers) and synthetic PICLas output; PICLas itself is not run in the tests

E_CHARGE = 1.602176634e-19
IONIZATION_K = 15.76 * EV / 1.380649e-23


def database() -> Database:
    db = Database(path='synthetic.h5', schema=Schema.SPECIES_DATABASE)
    for name, mass, charge, heat in (('Ar', 6.6335e-26, 0.0, 0.0), ('ArIon1', 6.6335e-26 - ELECTRON_MASS, E_CHARGE, IONIZATION_K), ('electron', ELECTRON_MASS, -E_CHARGE, 0.0)):
        db.species[name] = Species(name, {'MassIC': mass, 'ChargeIC': charge, 'InteractionID': 1, 'HeatOfFormation_K': heat})
    pair = CollisionPair('Ar-electron')
    pair.cross_sections.append(CrossSection(XSecKind.ELASTIC, 'ELASTIC', np.array([[0.0, 1.0e-20], [1000.0, 1.0e-20]])))
    pair.cross_sections.append(CrossSection(XSecKind.REACTION, 'ArIon1-electron-electron', np.array([[20.0, 1.0e-20], [1000.0, 3.0e-20]]), group='REACTION'))
    pair.cross_sections.append(CrossSection(XSecKind.REACTION, 'ArIon2-electron-electron-electron', np.array([[43.0, 0.0], [1000.0, 1.0e-21]]), group='REACTION'))
    db.collision_pairs['Ar-electron'] = pair
    return db


def test_threshold_as_in_piclas() -> None:
    db = database()
    assert heat_of_reaction(db, ['Ar', 'electron'], ['ArIon1', 'electron', 'electron']) == pytest.approx(15.76)
    data = as_used_by_piclas(db, np.array([[20.0, 1.0e-20], [100.0, 2.0e-20]]), ['Ar', 'electron'], ['ArIon1', 'electron', 'electron'])
    assert data[0].tolist() == pytest.approx([15.76, 0.0])
    assert heat_of_reaction(db, ['Ar', 'X'], ['ArIon1']) is None


def test_plan_beam() -> None:
    study = plan(database(), 'electron-Ar', None, [10.0, 17.88, 100.0], [], Settings())
    assert (study['target'], study['projectile'], study['mode']) == ('Ar', 'electron', 'beam')
    assert study['species'] == ['Ar', 'electron', 'ArIon1']
    assert study['skipped'] == ['ArIon2-electron-electron-electron: species ArIon2 not in the database']
    below, middle, high = study['points']
    assert not below['expected']['ArIon1-electron-electron'] > 0.0
    # at 17.88 eV: halfway between 15.76 eV (prepended zero) and 20 eV -> 0.5e-20 m^2
    velocity = math.sqrt(2.0 * 17.88 * EV / (ELECTRON_MASS * 6.6335e-26 / (6.6335e-26 + ELECTRON_MASS)))
    assert middle['expected']['ArIon1-electron-electron'] == pytest.approx(0.5e-20 * velocity, rel=1.0e-3)
    assert middle['events']['ArIon1-electron-electron'] >= 0.99e4
    assert high['steps'] >= 100


def test_plan_errors() -> None:
    db = database()
    with pytest.raises(ReservoirError, match='not in the database'):
        plan(db, 'Xe-electron', None, [10.0], [], Settings())
    with pytest.raises(ReservoirError, match='not part of'):
        plan(db, 'Ar-electron', 'Xe', [10.0], [], Settings())
    with pytest.raises(ReservoirError, match='not in Ar-electron'):
        plan(db, 'Ar-electron', None, [10.0], [], Settings(), ['ArIon3'])
    with pytest.raises(ReservoirError, match='no reaction'):
        plan(db, 'Ar-electron', None, [10.0], [], Settings(), ['ArIon2-electron-electron-electron'])
    del db.species['ArIon1'].attributes['MassIC']
    with pytest.raises(ReservoirError, match='MassIC'):
        plan(db, 'Ar-electron', None, [10.0], [], Settings())
    db.collision_pairs['Ar-electron'].cross_sections = db.collision_pairs['Ar-electron'].of_kind(XSecKind.ELASTIC)
    with pytest.raises(ReservoirError, match='no reaction cross-sections'):
        plan(db, 'Ar-electron', None, [10.0], [], Settings())


def write_output(directory: pathlib.Path, point: str, rates: list[float]) -> None:
    columns = ['001-TIME'] + [f'{index + 2:03d}-Reaction{index + 1:03d}' for index in range(len(rates))]
    lines = [','.join(columns), ','.join(['0'] * len(columns)), ','.join(['1.0E-9'] + [f'{rate:.14E}' for rate in rates])]
    (directory / point / 'PartAnalyze.csv').write_text('\n'.join(lines) + '\n')


def test_generate_and_evaluate(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / 'database.h5'
    write_database(database(), path)
    study_dir = tmp_path / 'study'
    assert main(['reservoir', str(path), '--pair', 'Ar-electron', '--energies', '10', '30', '100', '-o', str(study_dir)]) == 0
    assert 'skipped   ArIon2' in capsys.readouterr().out
    parameter = (study_dir / 'E_30eV' / 'parameter.ini').read_text()
    for line in (
        'Particles-DSMCReservoirSimRate    = T',
        'CalcReacRates    = T',
        'Part-Species2-Init1-velocityDistribution = constant',
        'DSMC-Reaction1-Reactants     = (/1,2,0/)',
        'DSMC-Reaction1-Products      = (/3,2,2,0/)',
        f'Particles-Species-Database = {path.resolve()}',
    ):
        assert line in parameter
    assert (study_dir / 'hopr.ini').is_file()
    assert (study_dir / 'run.sh').stat().st_mode & 0o100

    study = yaml.safe_load((study_dir / 'study.yaml').read_text())
    expected = {point['name']: point['expected']['ArIon1-electron-electron'] for point in study['points']}
    write_output(study_dir, 'E_10eV', [0.0])
    write_output(study_dir, 'E_30eV', [expected['E_30eV'] * 1.01])
    assert main(['reservoir', '--evaluate', str(study_dir)]) == 1  # E_100eV not run
    assert 'not run' in capsys.readouterr().out
    write_output(study_dir, 'E_100eV', [expected['E_100eV'] * 1.3])
    assert main(['reservoir', '--evaluate', str(study_dir)]) == 1
    assert 'FAILED' in capsys.readouterr().out
    write_output(study_dir, 'E_100eV', [expected['E_100eV'] * 0.98])
    assert main(['reservoir', '--evaluate', str(study_dir)]) == 0
    assert (study_dir / 'rates.png').is_file()
    results = evaluate(study_dir, 0.05)
    assert [result.passed for result in results] == [True, True, True]


def test_maxwell_and_command_errors(tmp_path: pathlib.Path) -> None:
    path = tmp_path / 'database.h5'
    write_database(database(), path)
    assert main(['reservoir', str(path), '--pair', 'Ar-electron', '--temperatures', '2e4:1e5:3', '-o', str(tmp_path / 'maxwell')]) == 0
    parameter = (tmp_path / 'maxwell' / 'T_20000K' / 'parameter.ini').read_text()
    assert 'Part-Species2-Init1-velocityDistribution = maxwell_lpn' in parameter
    assert 'Part-Species2-Init1-MWTemperatureIC      = 20000' in parameter
    assert main(['reservoir', str(path), '--pair', 'Ar-electron', '--temperatures', '2e4', '-o', str(tmp_path / 'maxwell')]) == 1  # not empty
    assert main(['reservoir', str(path), '--pair', 'Ar-electron', '-o', str(tmp_path / 'x')]) == 1  # neither energies nor temperatures
    assert main(['reservoir', str(path), '--pair', 'Ar-electron', '--energies', '-1', '-o', str(tmp_path / 'x')]) == 1
    assert main(['reservoir', str(tmp_path / 'missing.h5'), '--pair', 'Ar-electron', '--energies', '10', '-o', str(tmp_path / 'x')]) == 1
    assert main(['reservoir', '--evaluate', str(tmp_path)]) == 1  # no study.yaml
    broken = tmp_path / 'maxwell' / 'T_20000K' / 'PartAnalyze.csv'
    broken.write_text('001-TIME,002-Other\n0,0\n')
    assert main(['reservoir', '--evaluate', str(tmp_path / 'maxwell')]) == 1


def test_systematic_deviation_is_reported(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    # As in the first Ar study with PICLas: all points about -2.5 %, within the tolerance but beyond the counting statistics
    path = tmp_path / 'database.h5'
    write_database(database(), path)
    study_dir = tmp_path / 'study'
    assert main(['reservoir', str(path), '--pair', 'Ar-electron', '--energies', '50', '100', '--collision-probability', '0.05', '-o', str(study_dir)]) == 0
    study = yaml.safe_load((study_dir / 'study.yaml').read_text())
    assert study['settings']['collision_probability'] == pytest.approx(0.05)
    for point in study['points']:
        write_output(study_dir, point['name'], [point['expected']['ArIon1-electron-electron'] * 0.975])
    capsys.readouterr()
    assert main(['reservoir', '--evaluate', str(study_dir)]) == 0
    out = capsys.readouterr().out
    assert 'ok (systematic?)' in out
    assert 'systematic effect' in out
