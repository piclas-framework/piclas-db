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
from piclas_db.model import CollisionPair, CrossSection, Database, Provenance, Reaction, Species, XSecKind
from piclas_db.piclas_db import main
from piclas_db.reference import CM_TO_K, EV_TO_K
from piclas_db.rules import Finding, Severity, run_checks, significant_digits_at_most
from piclas_db.schema import Schema
# ==================================================================================================================================
# Every rule is tested with a small database that reproduces one problem found in existing files (synthetic data only)

REFERENCE = Provenance(reference='synthetic')
E_CHARGE = 1.602176634e-19


def rules_of(findings: list[Finding], severity: Severity) -> set[str]:
    return {finding.rule for finding in findings if finding.severity is severity}


def species_db(*species: Species, reactions: tuple[Reaction, ...] = ()) -> Database:
    db = Database(path='test.h5', schema=Schema.SPECIES_DATABASE)
    for spec in species:
        db.species[spec.name] = spec
    for reaction in reactions:
        db.reactions[reaction.name] = reaction
    return db


def xsec_db(*pairs: CollisionPair) -> Database:
    db = Database(path='test.h5', schema=Schema.LEGACY_XSEC)
    for pair in pairs:
        db.collision_pairs[pair.name] = pair
    return db


def xsec(kind: XSecKind, key: str, data: list[list[float]], group: str | None = None, **kwargs) -> CrossSection:
    return CrossSection(kind=kind, key=key, data=np.array(data, dtype=np.float64), group=group, provenance=Provenance(reference='synthetic'), **kwargs)


def levels(rows: list[list[float]]) -> np.ndarray:
    return np.array(rows, dtype=np.float64)


# ----------------------------------------------------------------------------------------------------------------------------------
# Species
# ----------------------------------------------------------------------------------------------------------------------------------
def test_clean_species_database() -> None:
    ar = Species('Ar', {'MassIC': 6.63e-26, 'InteractionID': 1}, levels([[1, 0], [5, 134013.1], [1, 127109.842 * CM_TO_K]]), provenance=REFERENCE)
    assert [finding.rule for finding in run_checks(species_db(ar))] == ['provenance-file']  # INFO: not written by piclas-db


def test_ion_masses() -> None:
    """Ion = parent minus n electron masses; one electron too many (CIon2 in SpeciesDatabase.h5) is reported in electron masses"""
    electron = 9.1e-31
    species = [
        Species('electron', {'MassIC': electron, 'InteractionID': 4}, provenance=REFERENCE),
        Species('Tx', {'MassIC': 2.0e-26, 'InteractionID': 1}, provenance=REFERENCE),
        Species('TxIon1', {'MassIC': 2.0e-26 - electron, 'InteractionID': 10}, provenance=REFERENCE),
        Species('TxIon2', {'MassIC': 2.0e-26 - 3 * electron, 'InteractionID': 10}, provenance=REFERENCE),
        Species('QqIon1', {'MassIC': 1.0e-26, 'InteractionID': 10}, provenance=REFERENCE),  # no parent: not checked
    ]
    findings = [finding for finding in run_checks(species_db(*species)) if finding.rule == 'species-ion-mass']
    assert len(findings) == 1 and findings[0].path.endswith('TxIon2') and 'minus 3.000 electron masses, the charge 2 needs 2' in findings[0].message


def test_attribute_typo_and_missing() -> None:
    fe = Species('Fe', {'MassIC': 9.27e-26, 'InteractionID': 1.0, 'alpha': 1.4, 'Comment2': 'x'}, provenance=REFERENCE)
    xe = Species('Xe', {'MassIC': 2.18e-25}, provenance=REFERENCE)
    findings = run_checks(species_db(fe, xe))
    messages = [finding.message for finding in findings if finding.rule == 'species-attribute-unknown']
    assert any("did you mean 'alphaVSS'" in message for message in messages)
    assert {'species-attribute-unknown', 'species-attribute-missing'} <= rules_of(findings, Severity.ERROR)
    assert 'species-attribute-type' in rules_of(findings, Severity.INFO)


def test_ground_state_degeneracy() -> None:
    ion = Species('ArIon1', {'MassIC': 6.63e-26, 'InteractionID': 10}, levels([[1, 0], [2, 2059.3]]), provenance=REFERENCE)
    assert 'levels-ground-state' in rules_of(run_checks(species_db(ion)), Severity.ERROR)


def test_ionization_limit_as_last_level() -> None:
    """PICLas takes the last level as ionization energy: a bound level there (SpeciesDatabase.h5: Ar) is reported"""
    limit = 13.598434 * EV_TO_K
    good = Species('H', {'MassIC': 1.67e-27, 'InteractionID': 1}, levels([[2, 0], [2, 118352.3], [1, limit]]), provenance=REFERENCE)
    bad = Species('H', {'MassIC': 1.67e-27, 'InteractionID': 1}, levels([[2, 0], [2, 118352.3], [6, 0.99 * limit]]), provenance=REFERENCE)
    assert 'levels-ionization-limit' not in rules_of(run_checks(species_db(good)), Severity.WARNING)
    assert 'levels-ionization-limit' in rules_of(run_checks(species_db(bad)), Severity.WARNING)


def test_missing_ground_state_and_unit() -> None:
    db = Database(path='old.h5', schema=Schema.LEGACY_ELECTRONIC)
    db.species['CNIon1'] = Species('CNIon1', electronic_levels=levels([[1, 128800.7], [1, 194298.6]]))
    # hydrogen levels in cm^-1 up to the ionization limit
    limit_cm = 13.598434 * EV_TO_K / CM_TO_K
    db.species['H'] = Species('H', electronic_levels=levels([[2, 0], [2, 82259.0], [1, limit_cm]]))
    findings = run_checks(db)
    assert {'levels-ground-state', 'levels-unit'} <= rules_of(findings, Severity.ERROR)
    assert 'provenance-missing' in rules_of(findings, Severity.WARNING)


def test_level_info_and_placeholders() -> None:
    ar = Species('Ar', {'MassIC': 6.63e-26, 'InteractionID': 1}, levels([[1, 0], [3, 140000], [5, 134000], [7, 134000]]), provenance=REFERENCE)
    dummy = Species('HIon1', {'MassIC': 1.67e-27, 'InteractionID': 10}, levels([[1, 0], [1, 1e32]]), provenance=REFERENCE)
    fe = Species('Fe', {'MassIC': 9.27e-26, 'InteractionID': 1}, electronic_placeholder=True, provenance=REFERENCE)
    electron = Species('electron', {'MassIC': 9.11e-31, 'InteractionID': 4}, electronic_placeholder=True, provenance=REFERENCE)
    findings = run_checks(species_db(ar, dummy, fe, electron))
    assert {'levels-unsorted', 'levels-duplicate', 'levels-dummy'} <= rules_of(findings, Severity.INFO)
    placeholders = [finding.path for finding in findings if finding.rule == 'levels-placeholder']
    assert placeholders == ['/Species/Fe/ElectronicLevel']


def test_levels_above_ionization_and_bad_values() -> None:
    above = Species('Ar', {'MassIC': 6.63e-26, 'InteractionID': 1}, levels([[1, 0], [1, 2.0e5], [1, 2.5e5]]), provenance=REFERENCE)
    bad = Species('C', {'MassIC': 2.0e-26, 'InteractionID': 1}, levels([[0.5, 0], [1, -1.0]]), provenance=REFERENCE)
    findings = run_checks(species_db(above, bad))
    assert 'levels-above-ionization' in rules_of(findings, Severity.WARNING)
    assert 'levels-values' in rules_of(findings, Severity.ERROR)


# ----------------------------------------------------------------------------------------------------------------------------------
# Reactions
# ----------------------------------------------------------------------------------------------------------------------------------
def test_reaction_conservation() -> None:
    me = 9.109e-31
    ar = Species('Ar', {'MassIC': 6.6335e-26, 'InteractionID': 1}, provenance=REFERENCE)
    ion = Species('ArIon1', {'MassIC': 6.6335e-26 - me * 1.5, 'ChargeIC': 2 * E_CHARGE, 'InteractionID': 10}, provenance=REFERENCE)
    electron = Species('electron', {'MassIC': me, 'ChargeIC': -E_CHARGE, 'InteractionID': 4}, provenance=REFERENCE)
    ionization = Reaction(
        'Ar+electron_ArIon1+electron+electron#1',
        {'Reactants': ['Ar', 'electron'], 'Products': ['ArIon1', 'electron', 'electron'], 'ReactionModel': ['XSec'], 'ChemistryModel': [['Ar', '']]},
    )
    unknown = Reaction('X_Y#1', {'Reactants': ['X'], 'Products': ['Y'], 'ReactionModel': 'TCE', 'ChemistryModel': [['m', '']]})
    findings = run_checks(species_db(ar, ion, electron, reactions=(ionization, unknown)))
    assert {'reaction-charge', 'reaction-species-missing', 'reaction-attribute-missing'} <= rules_of(findings, Severity.ERROR)
    assert 'reaction-mass' in rules_of(findings, Severity.WARNING)


# ----------------------------------------------------------------------------------------------------------------------------------
# Cross-sections
# ----------------------------------------------------------------------------------------------------------------------------------
def test_clean_cross_sections() -> None:
    pair = CollisionPair(
        'Xe-electron',
        [
            xsec(XSecKind.ELASTIC, 'ELASTIC', [[0.0, 1.234567e-19], [10.0, 2.345678e-19]]),
            xsec(XSecKind.ELECTRONIC, '8.315', [[8.315, 0.0], [20.0, 1.234567e-21]], group='ELECTRONIC', threshold=8.315),
            xsec(XSecKind.REACTION, 'XeIon1-electron-electron', [[12.13, 0.0], [50.0, 3.123456e-20]], group='REACTION', threshold=12.13),
        ],
    )
    assert run_checks(xsec_db(pair)) == []


def test_typo_ambiguity_and_double_counting() -> None:
    oxygen = CollisionPair(
        'O-electron',
        [
            xsec(XSecKind.UNKNOWN, '14', [[14.0, 0.0], [20.0, 1e-21]], group='ELECTRONIIC', threshold=14.0),
            xsec(XSecKind.UNKNOWN, '14.0', [[14.0, 0.0], [20.0, 2e-21]], group='ELECTRONIIC', threshold=14.0),
        ],
        empty_groups=['VIBRATION'],
    )
    dissociative = xsec(XSecKind.ELECTRONIC, '6.1', [[6.1, 0.0], [20.0, 1e-21]], group='ELECTRONIC', threshold=6.1)
    dissociative.provenance.extra['PROCESS'] = 'O2 -> O2( EXC A3 DISOC)'
    o2 = CollisionPair(
        'O2-electron',
        [
            dissociative,
            xsec(XSecKind.REACTION, 'O-electron-O', [[8.4, 0.0], [20.0, 1e-21]], group='REACTION'),
            xsec(XSecKind.REACTION, 'electron-O-O', [[6.0, 0.0], [23.0, 1e-21], [23.0, 2e-21]], group='REACTION'),
        ],
    )
    findings = run_checks(xsec_db(oxygen, o2))
    assert {'xsec-name-unknown', 'xsec-reaction-ambiguous'} <= rules_of(findings, Severity.ERROR)
    assert {'xsec-threshold-duplicate', 'xsec-double-counting', 'xsec-energy-duplicate', 'xsec-product-order'} <= rules_of(findings, Severity.WARNING)
    assert 'xsec-empty-group' in rules_of(findings, Severity.INFO)
    unknown = [finding for finding in findings if finding.rule == 'xsec-name-unknown']
    assert len(unknown) == 1
    assert "(2 datasets)" in unknown[0].message


def test_rounded_and_bad_data() -> None:
    energies = np.round(np.linspace(15.7, 16.5, 16), 1)  # rounded energies with many duplicates
    sigma = np.round(np.linspace(0.0, 1.0, 16), 2) * 1e-22
    reaction = CrossSection(XSecKind.REACTION, 'ArIon1-electron-electron', np.column_stack([energies, sigma]), group='REACTION', dtype='float32')
    cm2 = xsec(XSecKind.ELASTIC, 'ELASTIC', [[0.0, 1e-15], [1.0, 2e-15]])
    pair = CollisionPair('Ar-electron', [reaction, cm2])
    shape = CollisionPair('He-electron', [xsec(XSecKind.ELASTIC, 'ELASTIC', [[0.0, 1e-20]])])
    order = CollisionPair('Ne-electron', [xsec(XSecKind.ELASTIC, 'ELASTIC', [[1.0, 1e-20], [0.5, 1e-20]])])
    name = CollisionPair('N2-electron', [xsec(XSecKind.VIBRATION, 'v1', [[0.3, 0.0], [1.0, 1e-21]], group='VIBRATION')])
    findings = run_checks(xsec_db(pair, shape, order, name))
    assert {'xsec-energy-duplicate', 'xsec-shape', 'xsec-energy-order', 'xsec-threshold-name'} <= rules_of(findings, Severity.ERROR)
    assert {'xsec-magnitude', 'data-float32', 'provenance-missing'} <= rules_of(findings, Severity.WARNING)


def test_reaction_threshold_and_reversed_pair() -> None:
    reaction = xsec(XSecKind.REACTION, 'XeIon1-electron-electron', [[15.0, 5.5e-21], [20.0, 2.0e-20]], group='REACTION')
    pair = CollisionPair('Xe-electron', [reaction])
    reversed_pair = CollisionPair('electron-Xe', [xsec(XSecKind.ELASTIC, 'ELASTIC', [[0.0, 1e-19], [1.0, 2e-19]])])
    findings = run_checks(xsec_db(pair, reversed_pair))
    assert 'xsec-reaction-threshold' in rules_of(findings, Severity.WARNING)
    assert 'xsec-pair-duplicate' in rules_of(findings, Severity.ERROR)


def test_threshold_mismatch_and_undefined() -> None:
    pair = CollisionPair(
        'N2-electron',
        [
            xsec(XSecKind.ELECTRONIC, '6.17', [[6.2, 0.0], [10.0, 1e-21]], group='ELECTRONIC', threshold=6.5),
            xsec(XSecKind.UNDEFINED, '7.0', [[7.0, 0.0], [10.0, 1e-21]], group='UNDEFINED'),
        ],
    )
    findings = run_checks(xsec_db(pair))
    assert {'xsec-threshold-mismatch', 'xsec-undefined'} <= rules_of(findings, Severity.WARNING)


def test_significant_digits() -> None:
    assert significant_digits_at_most(np.array([1.03e-25, 3.63e-23, 0.0], dtype=np.float32).astype(np.float64), 3)
    assert not significant_digits_at_most(np.array([1.104590e-17]), 3)
    assert not significant_digits_at_most(np.array([0.0]), 3)


# ----------------------------------------------------------------------------------------------------------------------------------
# Command line
# ----------------------------------------------------------------------------------------------------------------------------------
def write_typo_file(path: pathlib.Path) -> None:
    with h5py.File(path, 'w') as h5:
        h5.create_dataset('O-electron/ELECTRONIIC/1.97', data=np.array([[1.97, 0.0], [10.0, 1.0e-21]]))


def test_check_exit_code_and_json(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / 'XSec_Database.h5'
    write_typo_file(path)
    assert main(['check', str(path)]) == 1
    assert "did you mean 'ELECTRONIC'" in capsys.readouterr().out
    assert main(['check', '--json', '--info', str(path)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report['layout'].startswith('legacy cross-section')
    assert any(finding['rule'] == 'xsec-name-unknown' for finding in report['findings'])
