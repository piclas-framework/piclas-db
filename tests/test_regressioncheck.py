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
import h5py
import numpy as np
import pytest

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.piclas_db import main
from piclas_db.plot import EV
from piclas_db.regressioncheck import RegressionCheckError, beam_rate, evaluate_check, number_of, values_of
# ==================================================================================================================================
# Synthetic regression check in the structure of the PICLas NIG_Reservoir checks (parameter.ini, analyze.ini, reference files)

ME, MAR = 9.11e-31, 6.634e-26
SIGMA = np.array([[15.76, 0.0], [100.0, 4.0e-20]])
TOTAL = np.array([[0.0, 1.0e-19], [1000.0, 1.0e-19]])
DT, N_BG = 2.0e-12, 1.0e23


def expected_reference(velocity: float) -> float:
    energy = 0.5 * ME * MAR / (ME + MAR) * velocity**2 / EV
    sigma = float(np.interp(energy, SIGMA[:, 0], SIGMA[:, 1], left=0.0))
    x = N_BG * (1.0e-19 + sigma) * velocity * DT
    return sigma * velocity * (1.0 - math.exp(-x)) / x  # as PICLas counts it


@pytest.fixture
def check(tmp_path: pathlib.Path) -> pathlib.Path:
    directory = tmp_path / 'CHEM_RATES_XSec_Chem_Ar-e'
    directory.mkdir()
    with h5py.File(directory / 'XSec_Database.h5', 'w') as h5:
        h5['Ar-electron/EFFECTIVE'] = TOTAL
        h5['Ar-electron/REACTION/ArIon1-electron-electron'] = SIGMA
    velocities = [2481019, 2965384, 4194262]
    (directory / 'parameter.ini').write_text(
        f"""ManualTimeStep = {DT}
CalcReacRates = T
Particles-CollXSec-Database = XSec_Database.h5
Part-nSpecies = 3
Part-Species1-SpeciesName = electron
Part-Species1-MassIC = {ME}
Part-Species1-Init1-SpaceIC = cell_local
Part-Species1-Init1-velocityDistribution = constant
Part-Species1-Init1-VeloIC = {', '.join(str(v) for v in velocities)}
Part-Species2-SpeciesName = Ar
Part-Species2-MassIC = {MAR}
Part-Species2-InteractionID = 1
Part-Species2-Init1-SpaceIC = background
Part-Species2-Init1-velocityDistribution = maxwell_lpn
Part-Species2-Init1-MWTemperatureIC = 300 ! background
Part-Species2-Init1-PartDensity = {N_BG}
Part-Species3-SpeciesName = ArIon1
Part-Species3-MassIC = {MAR - ME}
Part-Species3-Init1-MWTemperatureIC = crosscombinations
DSMC-NumOfReactions = 1
DSMC-Reaction1-ReactionModel = XSec
DSMC-Reaction1-Reactants = (/2,1,0/)
DSMC-Reaction1-Products = (/3,1,1,0/)
"""
    )
    names = [f'PartAnalyze_{v}_ref.csv' for v in velocities]
    (directory / 'analyze.ini').write_text(f'compare_data_file_reference = {", ".join(names)}\n')
    for name, velocity in zip(names, velocities, strict=True):
        (directory / name).write_text(f'001-TIME,002-Reaction001\n0,0\n1e-10,{expected_reference(velocity):.14E}\n')
    return directory


def test_parsing() -> None:
    assert number_of('2.0D-11 ! comment', None) == pytest.approx(2.0e-11)
    assert number_of('crosscombinations', 300.0) == pytest.approx(300.0)
    assert number_of(None, None) is None
    assert values_of('1, 2,abc, 3E2') == [1.0, 2.0, 300.0]


def test_evaluate_check(check: pathlib.Path) -> None:
    comparisons = evaluate_check(check)
    assert len(comparisons) == 3
    assert [round(comparison.energy, 1) for comparison in comparisons] == [17.5, 25.0, 50.0]
    for comparison in comparisons:
        assert comparison.deviation is not None and comparison.deviation < -0.01  # collision probability bias
        assert comparison.corrected == pytest.approx(0.0, abs=2.0e-3)  # removed by the correction


def test_rotational_energy_shift() -> None:
    # sigma ~ 1/sqrt(E): adding the rotational energy of two molecules at 300 K lowers the rate at 0.1 eV by about 19 %
    table = np.column_stack([np.logspace(-3, 2, 400), 1.0e-19 / np.sqrt(np.logspace(-3, 2, 400))])
    mass = 3.348e-27
    velocity = math.sqrt(2.0 * 0.1 * EV / (mass / 2.0))
    plain, _ = beam_rate(table, velocity, mass, mass, 300.0)
    rotating, _ = beam_rate(table, velocity, mass, mass, 300.0, (300.0, 300.0))
    assert rotating / plain == pytest.approx(0.82, abs=0.03)


def test_command(check: pathlib.Path, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(['reservoir', '--regressioncheck', str(check)]) == 0
    assert '3 comparisons' in capsys.readouterr().out
    empty = tmp_path / 'other.h5'
    with h5py.File(empty, 'w') as h5:
        h5['Ar-electron/EFFECTIVE'] = TOTAL
    assert main(['reservoir', str(empty), '--regressioncheck', str(check)]) == 1  # reaction cross-section missing
    assert 'not in the database' in capsys.readouterr().out
    (check / 'analyze.ini').write_text('')
    with pytest.raises(RegressionCheckError):
        evaluate_check(check)
    assert main(['reservoir', '--regressioncheck', str(tmp_path)]) == 0  # searches sub-directories, skips the broken check
