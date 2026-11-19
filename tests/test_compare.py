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
import h5py
import numpy as np
import pytest

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.compare import Change, compare
from piclas_db.model import CollisionPair, CrossSection, Database, Provenance, Reaction, Species, SurfaceEntry, XSecKind
from piclas_db.piclas_db import main
from piclas_db.reference import CM_TO_K
from piclas_db.schema import Schema
# ==================================================================================================================================
# Synthetic databases reproducing the differences found between existing files


def changes(comparison) -> dict[str, Change]:
    return {difference.path: difference.change for difference in comparison.differences}


def electronic_db(**levels: list[list[float]]) -> Database:
    db = Database(path='levels.h5', schema=Schema.LEGACY_ELECTRONIC)
    for name, rows in levels.items():
        db.species[name] = Species(name, electronic_levels=np.array(rows, dtype=np.float64))
    return db


def xsec_db(*cross_sections: CrossSection, pair: str = 'Xe-electron', reference: str | None = None) -> Database:
    db = Database(path='xsec.h5', schema=Schema.LEGACY_XSEC)
    db.collision_pairs[pair] = CollisionPair(pair, list(cross_sections), provenance=Provenance(reference=reference))
    return db


def curve(kind: XSecKind, key: str, data: list[list[float]], group: str | None = None, reference: str | None = None) -> CrossSection:
    return CrossSection(kind, key, np.array(data, dtype=np.float64), group=group, provenance=Provenance(reference=reference))


ELASTIC = [[0.0, 1.0e-19], [1.0, 2.0e-19], [10.0, 3.0e-19]]


def test_identical_including_float32_rounding() -> None:
    a = xsec_db(curve(XSecKind.ELASTIC, 'ELASTIC', ELASTIC))
    b = xsec_db(curve(XSecKind.ELASTIC, 'ELASTIC', np.array(ELASTIC, dtype=np.float32).astype(np.float64).tolist()))
    comparison = compare(a, b)
    assert comparison.equal
    assert comparison.identical == 1


def test_levels_scaled_degeneracy_and_ground_state() -> None:
    a = electronic_db(Ar=[[1, 0], [5, 133982.9], [3, 134855.8]], ArIon1=[[4, 0], [2, 2059.3]], H=[[2, 0], [2, 82259.0], [2, 97492.2]])
    b = electronic_db(
        Ar=[[1, 0], [5, 133982.9 * 1.000193], [3, 134855.8 * 1.000193]],
        ArIon1=[[1, 0], [2, 2059.3]],
        H=[[2, 0], [2, 82259.0 * CM_TO_K], [2, 97492.2 * CM_TO_K], [2, 102823.9 * CM_TO_K]],
        CNIon1=[[1, 0], [1, 1.0]],
    )
    comparison = compare(a, b)
    result = changes(comparison)
    assert result['/Species/Ar/ElectronicLevel'] is Change.SCALED
    assert result['/Species/ArIon1/ElectronicLevel'] is Change.NUMERIC
    assert result['/Species/CNIon1'] is Change.ONLY_IN_B
    messages = {difference.path: difference.message for difference in comparison.differences}
    assert '4 -> 1' in messages['/Species/ArIon1/ElectronicLevel']
    assert 'scaled by 1.43877' in messages['/Species/H/ElectronicLevel']


def test_levels_missing_ground_state_and_placeholder() -> None:
    a = electronic_db(CNIon1=[[1, 128800.7], [1, 194298.6], [1, 200000.0]])
    b = electronic_db(CNIon1=[[1, 0], [1, 128800.7], [1, 200000.0], [1, 210000.0]])
    a.species['Xe'] = Species('Xe', electronic_placeholder=True)
    b.species['Xe'] = Species('Xe', electronic_levels=np.array([[1.0, 0.0], [5.0, 96491.0]]))
    comparison = compare(a, b)
    messages = {difference.path: difference.message for difference in comparison.differences}
    assert 'lowest level' in messages['/Species/CNIon1/ElectronicLevel']
    assert changes(comparison)['/Species/Xe/ElectronicLevel'] is Change.STRUCTURE
    assert messages['/Species/Xe/ElectronicLevel'] == 'placeholder in A, 2 levels in B'


def test_levels_missing_in_one_file() -> None:
    a = electronic_db(Ar=[[1, 0], [5, 133982.9]])
    b = Database(path='levels.h5', schema=Schema.LEGACY_ELECTRONIC)
    b.species['Ar'] = Species('Ar')
    comparison = compare(a, b)
    assert not comparison.equal and comparison.identical == 0
    assert [difference.message for difference in comparison.differences] == ['2 levels in A, no levels in B']


def test_cross_sections_renamed_typo_and_sources() -> None:
    a = xsec_db(
        curve(XSecKind.REACTION, 'electron-electron-XeIon1', [[12.13, 0.0], [50.0, 3.0e-20]], group='REACTION', reference='Biagi-v7.1 database, retrieved 2025'),
        curve(XSecKind.UNKNOWN, '9.447', [[9.447, 0.0], [20.0, 1.0e-21]], group='ELECTRONIIC'),
        curve(XSecKind.ELASTIC, 'ELASTIC', ELASTIC, reference='Biagi-v7.1 database, retrieved 2025'),
    )
    b = xsec_db(
        curve(XSecKind.REACTION, 'XeIon1-electron-electron', [[12.13, 0.0], [50.0, 3.0e-20]], group='REACTION'),
        curve(XSecKind.ELECTRONIC, '9.447', [[9.447, 0.0], [20.0, 1.0e-21]], group='ELECTRONIC'),
        curve(XSecKind.ELASTIC, 'ELASTIC', [[0.0, 1.0e-19], [5.0, 2.5e-19], [10.0, 2.0e-19]], reference='Hayashi database, retrieved 2020'),
        pair='electron-Xe',
    )
    comparison = compare(a, b)
    kinds = [difference.change for difference in comparison.differences]
    assert kinds.count(Change.RENAMED) == 3  # pair order (electron-Xe matches Xe-electron), product order, typo in the group name
    elastic = next(d for d in comparison.differences if d.path.endswith('ELASTIC'))
    assert elastic.change is Change.NUMERIC
    assert elastic.different_source


def test_cross_sections_scaled_regridded_and_only_in_one() -> None:
    a = xsec_db(
        curve(XSecKind.ELASTIC, 'ELASTIC', ELASTIC),
        curve(XSecKind.EFFECTIVE, 'EFFECTIVE', ELASTIC),
        curve(XSecKind.ELECTRONIC, '6.1', [[6.1, 0.0], [20.0, 1e-21]], group='ELECTRONIC'),
    )
    b = xsec_db(
        curve(XSecKind.ELASTIC, 'ELASTIC', (np.array(ELASTIC) * [1.0, 1.0e4]).tolist()),
        curve(XSecKind.EFFECTIVE, 'EFFECTIVE', [[0.0, 1.0e-19], [0.5, 1.5e-19], [1.0, 2.0e-19], [10.0, 3.0e-19]]),
        curve(XSecKind.BACKSCATTER, 'BACKSCATTER', ELASTIC),
    )
    result = changes(compare(a, b))
    assert result['/Cross-Sections/Xe-electron/ELASTIC'] is Change.SCALED
    assert result['/Cross-Sections/Xe-electron/EFFECTIVE'] is Change.STRUCTURE
    assert result['/Cross-Sections/Xe-electron/ELECTRONIC/6.1'] is Change.ONLY_IN_A
    assert result['/Cross-Sections/Xe-electron/BACKSCATTER'] is Change.ONLY_IN_B


def test_reactions_attributes_and_scope() -> None:
    a = Database(path='a.h5', schema=Schema.SPECIES_DATABASE)
    b = Database(path='b.h5', schema=Schema.SPECIES_DATABASE)
    a.species['Fe'] = Species('Fe', {'MassIC': 9.27e-26, 'alpha': 1.4})
    b.species['Fe'] = Species('Fe', {'MassIC': 9.27e-26, 'alphaVSS': 1.4})
    a.reactions['R#1'] = Reaction('R#1', {'ReactionModel': ['TCE'], 'Arrhenius-Prefactor': 1.0e-16})
    b.reactions['R#1'] = Reaction('R#1', {'ReactionModel': 'TCE', 'Arrhenius-Prefactor': 2.0e-16})
    b.surface['StickingCoefficient'] = SurfaceEntry('StickingCoefficient', data=np.ones((2, 4)))
    comparison = compare(a, b)
    messages = [difference.message for difference in comparison.differences]
    assert "attribute 'alpha' only in A" in messages
    assert any('Arrhenius-Prefactor' in message for message in messages)
    assert not any('ReactionModel' in message for message in messages)  # array and string with the same content are equal
    assert comparison.skipped == ['diffusion and surface data (only in B)']
    assert 'diffusion and surface data' in compare(a, b, everything=True).compared


# ----------------------------------------------------------------------------------------------------------------------------------
# Command line
# ----------------------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def files(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    old, new = tmp_path / 'DSMCSpecies_electronic_state.h5', tmp_path / 'SpeciesDatabase.h5'
    with h5py.File(old, 'w') as h5:
        h5.create_dataset('Ar', data=np.array([[1.0, 0.0], [5.0, 133982.9]]))
        h5.create_dataset('NCO', data=np.array([[2.0, 0.0], [2.0, 1000.0]]))
    with h5py.File(new, 'w') as h5:
        group = h5.create_group('Species/Ar')
        group.attrs['MassIC'] = 6.63e-26
        group.create_dataset('ElectronicLevel', data=np.array([[1.0, 0.0], [5.0, 133982.9]], dtype=np.float32))
        h5.create_dataset('Cross-Sections/Ar-electron/ELASTIC', data=np.array(ELASTIC))
    return old, new


def test_diff_command(files: tuple[pathlib.Path, pathlib.Path], capsys: pytest.CaptureFixture[str]) -> None:
    old, new = files
    assert main(['diff', str(new), str(new)]) == 0
    assert main(['diff', str(old), str(new)]) == 1
    output = capsys.readouterr().out
    assert 'species only in A' in output
    assert 'not compared: cross-sections (only in B)' in output
    assert main(['diff', '--json', '--all', str(old), str(new)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert {difference['change'] for difference in report['differences']} == {'only in A', 'only in B'}
    assert main(['diff', str(old), str(old.parent / 'missing.h5')]) == 2


def test_vibrational_levels() -> None:
    a = Database(path='a.h5', schema=Schema.SPECIES_DATABASE)
    b = Database(path='b.h5', schema=Schema.SPECIES_DATABASE)
    a.species['Tx'] = Species('Tx', vibrational_levels=np.array([[0.0], [3000.0], [6000.0]]))
    b.species['Tx'] = Species('Tx')
    a.species['Qq'] = Species('Qq', vibrational_levels=np.array([[0.0], [1000.0]]))
    b.species['Qq'] = Species('Qq', vibrational_levels=np.array([[0.0], [1001.0]]))
    messages = {difference.path: difference.message for difference in compare(a, b).differences}
    assert messages == {'/Species/Tx/VibrationalLevel': '3 levels in A, no levels in B', '/Species/Qq/VibrationalLevel': '1 energies differ (max relative deviation 1.00e-03)'}


def test_diff_table_on_terminal(files: tuple[pathlib.Path, pathlib.Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """On a terminal: one table per section with name, item, change, A, B and relative difference; plain lines otherwise"""
    from piclas_db.commands import diff  # noqa: PLC0415

    main(['diff', str(files[0]), str(files[1])])
    plain = capsys.readouterr().out
    assert '┌' not in plain
    monkeypatch.setattr(diff, 'interactive', lambda: True)
    monkeypatch.setattr(diff, 'use_color', lambda: False)
    monkeypatch.setenv('COLUMNS', '100')
    main(['diff', str(files[0]), str(files[1])])
    table = capsys.readouterr().out
    assert '┌' in table and '│ Name' in table and 'B/A - 1' in table
    assert all(len(line) <= 100 for line in table.splitlines() if line.startswith(('┌', '│', '├', '└')))
    assert plain.splitlines()[-1] == table.splitlines()[-1]  # same summary


def test_table_lines_structured() -> None:
    from piclas_db.commands.diff import table_lines  # noqa: PLC0415

    a = Database(path='a.h5', schema=Schema.SPECIES_DATABASE)
    b = Database(path='b.h5', schema=Schema.SPECIES_DATABASE)
    a.species['Tx'] = Species('Tx', {'MassIC': 2.0e-26, 'Tref': 273.0, 'Old': 1.0})
    b.species['Tx'] = Species('Tx', {'MassIC': 2.0002e-26, 'Tref': 273.0, 'New': 2.0})
    lines = table_lines(compare(a, b).differences, width=90)
    text = '\n'.join(lines)
    assert lines[0] == 'Species (3)' and '+1.00e-04' in text and '2.0002e-26' in text
    assert 'only in B' in [cell.strip() for cell in next(line for line in lines if 'New' in line).split('│')]
    assert 'only in A' in [cell.strip() for cell in next(line for line in lines if 'Old' in line).split('│')]
    narrow = table_lines(compare(a, b).differences, width=50)
    assert all(len(line) <= 50 for line in narrow[1:])


def test_levels_order_and_degeneracies_per_energy() -> None:
    """Multiplet-ordered levels (as in SpeciesDatabase.h5) equal the same levels sorted by energy; the order of levels with the same
    energy does not matter, only the sum of their degeneracies"""
    unsorted = [[2, 0.0], [2, 1000.0], [4, 1000.5], [2, 1000.1], [3, 2000.0], [5, 2000.0]]
    ordered = [[2, 0.0], [2, 1000.0], [2, 1000.1], [4, 1000.5], [5, 2000.0], [3, 2000.0]]
    assert compare(electronic_db(Tx=unsorted), electronic_db(Tx=ordered)).equal
    changed = [[2, 0.0], [2, 1000.0], [2, 1000.1], [4, 1000.5], [5, 2000.0], [5, 2000.0]]
    messages = [difference.message for difference in compare(electronic_db(Tx=unsorted), electronic_db(Tx=changed)).differences]
    assert messages == ['1 degeneracies differ (first: at 2000 K, 8 -> 10)']
