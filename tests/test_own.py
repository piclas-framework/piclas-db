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
from piclas_db.readers import read_database
from piclas_db.recipe import RecipeError, load_recipe, parse_recipe
from piclas_db.sources.own import OwnDataError, own_data_from_database, parse_own_data
from piclas_db.sources.identify import IdentifyError, identify
from piclas_db.store import Store
# ==================================================================================================================================

OWN = """format: piclas-db own data
format_version: 1
name: PICLas parameters
description: test values (invented)
species:
  Ar: {Tref: 273, dref: 4.0e-10, omega: 0.31, alphaVSS: 1.4, InteractionID: 1, MassIC: 6.6e-26, Reference: "Book 1994, Table A1"}
  N2: {Tref: 273, dref: 4.1e-10, omega: 0.24, InteractionID: 2, CharaTempVib: 3393.3, Reference: "Book 1994; Tables 1979"}
"""


def test_own_data_file(tmp_path: pathlib.Path) -> None:
    path = tmp_path / 'own.yaml'
    path.write_text(OWN)
    identified = identify(path)
    assert (identified.provider, identified.kind, identified.dataset) == ('own', 'species-parameters', 'piclas-parameters')
    assert identified.species == ['Ar', 'N2']
    for text, message in (
        (OWN.replace('  N2: {Tref: 273, dref: 4.1e-10, omega: 0.24, InteractionID: 2, CharaTempVib: 3393.3, Reference: "Book 1994; Tables 1979"}', '  N2: {Tref: 273}'), 'N2: "Reference" missing'),
        (OWN.replace('name: PICLas parameters\n', ''), '"name" required'),
        (OWN.replace('format_version: 1', 'format_version: 9'), 'newer'),
        ('format: piclas-db own data\nname: x\nspecies: {}\n', 'at least one species'),
        ('format: piclas-db own data\n  : [', 'YAML'),
    ):
        path.write_text(text)
        with pytest.raises(IdentifyError, match=message):
            identify(path)


def test_build_with_own_data(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = tmp_path / 'store'
    (tmp_path / 'own.yaml').write_text(OWN)
    assert main(['import', str(tmp_path / 'own.yaml'), '--store', str(store)]) == 0
    assert Store(store).entries()[0].meta['imported_by'] == 'piclas-db test <test@example.com>'
    recipe = tmp_path / 'recipe.yaml'
    recipe.write_text('own_data: own/piclas-parameters\nspecies:\n  Ar: {}\n  N2: {omega: 0.25}\n  O2: {}\n')
    output = tmp_path / 'database.h5'
    capsys.readouterr()
    assert main(['build', str(recipe), '-o', str(output), '--store', str(store), '--offline']) == 0
    out = capsys.readouterr().out
    assert 'N2: omega written in the recipe, not in the store' in out and 'O2: not in the own data' in out
    database = read_database(output)
    ar, n2 = database.species['Ar'], database.species['N2']
    assert ar.attributes['alphaVSS'] == pytest.approx(1.4) and ar.attributes['InteractionID'] == 1
    assert n2.attributes['omega'] == pytest.approx(0.25)  # the recipe takes precedence
    assert n2.attributes['CharaTempVib'] == pytest.approx(3393.3)
    assert ar.provenance.reference == 'Book 1994, Table A1' and 'own/piclas-parameters' in str(ar.provenance.extra['* Source'])
    assert 'Reference' not in ar.attributes  # the reference is provenance, not a PICLas attribute

    for text, message in (('own_data: lxcat/x/y\n', 'own/<name>'), ('own_data: [nothing]\n', 'provider')):
        recipe.write_text(text)
        with pytest.raises(RecipeError, match=message):
            load_recipe(recipe)
    recipe.write_text('own_data: own/missing\nspecies:\n  Ar: {}\n')
    assert main(['build', str(recipe), '-o', str(output), '--store', str(store), '--offline', '--force']) == 1  # not in the store


# ----------------------------------------------------------------------------------------------------------------------------------
# Own data from an existing database (export --own-data)
# ----------------------------------------------------------------------------------------------------------------------------------
def old_database(path: pathlib.Path) -> pathlib.Path:
    """Synthetic file in the layout of SpeciesDatabase.h5: tabular and plain references, an unknown source, a species named NO"""
    with h5py.File(path, 'w') as h5:
        rows = np.array([[b'HeatOfFormation', b' Tables 1.0'], [b'Moments of Inertia [kg * m^2]', b' Constants Book 2001']], dtype='S100')
        attributes: dict[str, tuple[dict, object]] = {
            'Xy': ({'MassIC': 5.0e-26, 'ChargeIC': 0.0, 'HeatOfFormation_K': 0.0, 'InteractionID': 1.0, 'Tref': 273.0, 'dref': 4.0e-10, 'omega': 0.24}, 'HeatOfFormation: ATcT 9.9'),
            'NO': (
                {
                    'MassIC': 4.9e-26,
                    'HeatOfFormation_K': 10.5,
                    'InteractionID': 2.0,
                    'CharaTempVib': np.array([100.0, 200.0]),
                    'MomentOfInertia': 1.0e-46,
                    'LinearMolec': np.int32(1),
                    'Tref': 273.0,
                    'dref': 4.2e-10,
                    'omega': 0.24,
                },
                rows,
            ),
            'XyIon2': ({'MassIC': 4.99e-26, 'ChargeIC': 3.2e-19, 'InteractionID': 10, 'PreviousState': b'XyIon1', 'Tref': 300.0, 'dref': 3.0e-10, 'omega': 0.2}, 'Unknown'),
            'Zz': (
                {'MassIC': 9.0e-26, 'HeatOfFormation_K': 500.0, 'InteractionID': 1.0, 'Tref': 1000.0, 'dref': 5.0e-10, 'omega': 0.3},
                'HeatOfFormation: Thermo Book (1998); A. Author. A paper: part 2. Journal, 1(2):3–4, 1997.',
            ),
            'Ww': (
                {'MassIC': 8.0e-26, 'HeatOfFormation_K': 7.0, 'InteractionID': 1, 'Tref': 300.0, 'dref': 4.0e-10, 'omega': 0.2},
                np.array([[b'Electronic Energy Levels', b'Spectra Database'], [b'HeatOfFormation_K', b'ATcT 9.9; online'], [b'MassIC', b'ATcT 9.9; online'], [b'Tref', b'User input']], dtype='S50'),
            ),
        }
        for name, (values, reference) in attributes.items():
            group = h5.create_group(f'Species/{name}')
            for key, value in values.items():
                group.attrs[key] = value
            group.attrs['* Reference'] = reference
            group.attrs['* Created'] = 'January 01, 2020'
            group.create_dataset('ElectronicLevel', data=np.array([[1.0, 0.0], [3.0, 100.0]]))
    return path


def test_reference_rows_readable(tmp_path: pathlib.Path) -> None:
    database = read_database(old_database(tmp_path / 'old.h5'))
    provenance = database.species['NO'].provenance
    assert provenance.reference == 'HeatOfFormation: Tables 1.0; Moments of Inertia [kg * m^2]: Constants Book 2001'
    assert provenance.reference_parts[1] == ('Moments of Inertia [kg * m^2]', 'Constants Book 2001')
    assert database.species['Xy'].provenance.reference_parts == []


def test_own_data_from_database(tmp_path: pathlib.Path) -> None:
    export = own_data_from_database(read_database(old_database(tmp_path / 'old.h5')), 'old.h5 (2020-01-01)')
    species = export.content['species']
    assert sorted(export.atct_species) == ['Ww', 'Xy'] and export.left_out['Xy'] == ['HeatOfFormation_K', 'MassIC']
    assert 'MassIC' not in species['Xy'] and 'HeatOfFormation_K' not in species['Ww']
    assert species['Xy']['Reference'] == 'old.h5 (2020-01-01); source unknown: ChargeIC, InteractionID, Tref, dref, omega'
    assert species['Ww']['Reference'] == 'old.h5 (2020-01-01); Tref: User input; source unknown: InteractionID, dref, omega'
    assert species['NO']['Reference'] == ('old.h5 (2020-01-01); HeatOfFormation_K: Tables 1.0; MomentOfInertia: Constants Book 2001; source unknown: MassIC, InteractionID, Tref, dref, omega, CharaTempVib, LinearMolec')
    assert species['NO']['CharaTempVib'] == [100.0, 200.0] and species['XyIon2']['PreviousState'] == 'XyIon1'
    assert species['Zz']['Reference'] == (
        'old.h5 (2020-01-01); HeatOfFormation_K: Thermo Book (1998); not stated which of MassIC, InteractionID, Tref, dref, omega come from: A. Author. A paper: part 2. Journal, 1(2):3–4, 1997.'
    )
    assert export.unknown['XyIon2'] == ['MassIC', 'ChargeIC', 'InteractionID', 'PreviousState', 'Tref', 'dref', 'omega']
    kept = own_data_from_database(read_database(tmp_path / 'old.h5'), 'old.h5', keep_atct=True).content['species']
    assert kept['Xy']['MassIC'] == pytest.approx(5.0e-26, rel=0) and kept['Xy']['Reference'] == 'old.h5; HeatOfFormation_K: ATcT 9.9; source unknown: MassIC, ChargeIC, InteractionID, Tref, dref, omega'
    assert kept['Ww']['Reference'].startswith('old.h5; HeatOfFormation_K: ATcT 9.9; online; MassIC: ATcT 9.9; online; Tref: User input')


def test_export_own_data_round_trip(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    """export --own-data --keep-atct, import, build: the species attributes of the old file again (values and integer/float type)"""
    old = old_database(tmp_path / 'old.h5')
    own = tmp_path / 'own.yaml'
    assert main(['export', str(old), '--own-data', str(own), '--origin', 'old.h5 (2020-01-01)', '--keep-atct']) == 0
    assert '5 species' in capsys.readouterr().out
    assert "\n  'NO': {" in own.read_text()  # quoted: YAML reads NO as false
    assert main(['export', str(old), '--own-data', str(own)]) == 1 and 'exists' in capsys.readouterr().out
    assert main(['export', str(old)]) == 1 and '--own-data' in capsys.readouterr().out
    store = tmp_path / 'store'
    assert main(['import', str(own), '--store', str(store)]) == 0
    recipe = tmp_path / 'recipe.yaml'
    recipe.write_text('own_data: own/piclas-parameters\nspecies:\n' + ''.join(f"  '{name}': {{}}\n" for name in ('NO', 'Ww', 'Xy', 'XyIon2', 'Zz')))
    output = tmp_path / 'new.h5'
    assert main(['build', str(recipe), '-o', str(output), '--store', str(store), '--offline']) == 0
    before, after = read_database(old), read_database(output)
    for name, species in before.species.items():
        rebuilt = after.species[name].attributes
        assert set(rebuilt) == set(species.attributes), name
        for key, value in species.attributes.items():
            assert np.array_equal(np.asarray(rebuilt[key]), np.asarray(value)) and np.asarray(rebuilt[key]).dtype.kind == np.asarray(value).dtype.kind, (name, key)
    assert str(after.species['Xy'].provenance.reference).startswith('old.h5 (2020-01-01); HeatOfFormation_K: ATcT 9.9')


def test_unquoted_yaml_names(tmp_path: pathlib.Path) -> None:
    with pytest.raises(OwnDataError, match='read by YAML as bool'):
        parse_own_data('format: piclas-db own data\nname: x\nspecies:\n  NO: {Tref: 273, Reference: Book}\n')
    with pytest.raises(RecipeError, match='write it in quotes'):
        parse_recipe('species:\n  NO: {}\n', 'test')
    with pytest.raises(RecipeError, match='read by YAML as bool'):
        parse_recipe('levels:\n  - source: nist-asd/levels/no\n    species: NO\n', 'test')
    assert list(parse_recipe("species:\n  'NO': {}\n", 'test').species) == ['NO']


def test_export_own_data_atct_from(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    """--atct-from: species with an ATcT ID in the recipe lose heat of formation and mass too (masses of one source)"""
    old = old_database(tmp_path / 'old.h5')
    recipe = tmp_path / 'atct.yaml'
    recipe.write_text("species:\n  XyIon2: {atct: 1-1-1*0}\n  Zz: {atct: 2-2-2*0}\n  'NO': {}\n")
    own = tmp_path / 'own.yaml'
    assert main(['export', str(old), '--own-data', str(own), '--atct-from', str(recipe)]) == 0
    assert 'also for XyIon2, Zz: --atct-from' in capsys.readouterr().out
    species = parse_own_data(own.read_text())['species']
    assert 'MassIC' not in species['XyIon2'] and 'HeatOfFormation_K' not in species['Zz'] and 'MassIC' in species['NO']
    assert 'Thermo Book' not in species['Zz']['Reference']  # the source of the value that was left out
    assert main(['export', str(old), '--own-data', str(own), '--force', '--atct-from', str(recipe), '--keep-atct']) == 1


def test_build_notes_own_value_over_atct(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    import json  # noqa: PLC0415

    store = tmp_path / 'store'
    (tmp_path / 'own.yaml').write_text(OWN)
    item = {'ATcT_TN_Version': '9.999', 'ATcT_ID': '111-11-1*0', 'Name': 'Testium', 'Formula': 'Ar  (g)', '∆fH_298K': '0', 'mass': 40.0, 'charge': 0}
    (tmp_path / 'record.json').write_text(json.dumps(item, ensure_ascii=False))
    assert main(['import', str(tmp_path / 'own.yaml'), str(tmp_path / 'record.json'), '--store', str(store), '--retrieved', '2026-01-01']) == 0
    recipe = tmp_path / 'recipe.yaml'
    recipe.write_text('own_data: own/piclas-parameters\nspecies:\n  Ar: {atct: 111-11-1*0}\n')
    capsys.readouterr()
    assert main(['build', str(recipe), '-o', str(tmp_path / 'db.h5'), '--store', str(store), '--offline']) == 0
    assert 'Ar: MassIC from the own data or recipe (6.6e-26), not from ATcT 111-11-1*0' in capsys.readouterr().out
