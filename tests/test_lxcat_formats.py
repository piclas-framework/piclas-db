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
import zipfile

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
from piclas_db.sources.any import read_any
from piclas_db.sources.identify import IdentifyError, identify
from piclas_db.sources.lxcat import canonical_parameters, canonical_process, compare, load_lxcat, parse_lxcat, parse_lxcat_xml
from piclas_db.store import Store
from tests.test_import import LXCAT
# ==================================================================================================================================
# The synthetic LXCat download of test_import.py, also as XML in the structure of LXCat (version 1.1), and as ZIP with both

XML = """<?xml version="1.0" encoding="utf-8"?>
<lxcat version="1.1" created="2026-06-01 10:00:00" message="ATTENTION: downloading in xml format in under development."><References>
<Source>LXCat, www.lxcat.net. Generated on 01 Jun 2026. All rights reserved.</Source>
<Reference>- Test-A database, www.lxcat.net, retrieved on June 1, 2026.</Reference>
<Reference>- Test-B database, www.lxcat.net, retrieved on June 1, 2026.</Reference></References>
<Database name="Test-A (version 1)" id="Test-A"><Permlink>www.lxcat.net/Test-A</Permlink><Groups><Group><Processes>
<Process class="Scattering Cross Sections" type="Elastic"><Species><Reactant>e</Reactant><Reactant>Ar</Reactant><Product> E</Product><Product>Ar</Product></Species>
<Reaction>E + Ar -&gt; E + Ar</Reaction><Parameters><mM>1.000000e-5</mM><Parameter>complete set</Parameter></Parameters><Comment>invented numbers</Comment>
<Updated>2020-01-01 00:00:00</Updated><DataX type="Energy" units="eV" size="2">0.000000e+0 1.000000e+1</DataX><DataY type="Cross section" units="m2" size="2">1.000000e-20 2.000000e-20</DataY></Process>
<Process class="Scattering Cross Sections" type="Ionization"><Species><Reactant>e</Reactant><Reactant>Ar</Reactant><Product> E</Product><Product>E</Product><Product>Ar^+</Product></Species>
<Reaction>E + Ar -&gt; E + E + Ar^+</Reaction><Parameters><E>1.570000e+1</E><Parameter>complete set</Parameter></Parameters>
<DataX type="Energy" units="eV" size="2">1.570000e+1 1.000000e+2</DataX><DataY type="Cross section" units="m2" size="2">0.000000e+0 3.000000e-20</DataY></Process>
</Processes></Group></Groups></Database>
<Database name="Test-B database" id="Test-B"><Permlink>www.lxcat.net/Test-B</Permlink><Groups><Group><Processes>
<Process class="Scattering Cross Sections" type="Backscat"><Species><Reactant>Ar^+</Reactant><Reactant>Ar</Reactant></Species>
<Reaction>Ar^+ + Ar -&gt;</Reaction><Parameters><Mi>3.994800e+1</Mi><MiM>1.000000e+0</MiM><Parameter>complete set</Parameter></Parameters>
<Comment>first comment second comment</Comment><Updated>2011-10-30 07:03:24</Updated>
<DataX type="Energy" units="eV" size="2">0.000000e+0 1.000000e+0</DataX><DataY type="Cross section" units="m2" size="2">1.000000e-18 5.000000e-19</DataY></Process>
</Processes></Group></Groups></Database></lxcat>
"""
RECIPE = """cross_sections:
  - source: {source}
    database: Test-A
    species: e / Ar
  - source: {source}
    database: Test-B
    species: Ar^+ / Ar
    types: {{Backscat: BACKSCATTER}}
"""


def zipped(path: pathlib.Path, files: dict[str, str]) -> pathlib.Path:
    with zipfile.ZipFile(path, 'w') as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return path


def test_canonical_forms() -> None:
    assert canonical_process('Ar^+ + Ar -> , Backscat') == canonical_process('Ar+ + Ar ->, Backscat') == 'Ar+ + Ar ->, Backscat'
    assert canonical_parameters('m/M = 0.0000136, complete set') == canonical_parameters('m/M = 1.36e-5, complete set') == 'm/M = 1.36e-05, complete set'
    assert canonical_parameters('E = 15.70 eV, complete set') == 'E = 15.7 eV, complete set'


def test_txt_and_xml_are_the_same(tmp_path: pathlib.Path) -> None:
    txt, xml = parse_lxcat(LXCAT), parse_lxcat_xml(XML)
    assert compare(txt, xml) == []
    assert xml.references == txt.references and xml.generated == txt.generated
    assert [process.type for process in xml.processes] == ['ELASTIC', 'IONIZATION', 'Backscat']
    changed = parse_lxcat_xml(XML.replace('3.000000e-20', '3.100000e-20'))
    assert compare(txt, changed) == ['test-a e/Ar E + Ar -> E + E + Ar+, Ionization: data differ (2 / 2 points)']
    with pytest.raises(ValueError, match='cannot be read'):
        parse_lxcat_xml('<lxcat><Database')
    with pytest.raises(ValueError, match='energies but'):
        parse_lxcat_xml(XML.replace('0.000000e+0 1.000000e+1', '0.000000e+0'))
    with pytest.raises(ValueError, match='unit'):
        parse_lxcat_xml(XML.replace('units="m2" size="2">1.000000e-20', 'units="cm2" size="2">1.000000e-20'))

    both = zipped(tmp_path / 'download.zip', {'Cross section.txt': LXCAT, 'Cross section.xml': XML, 'Cross section.png': 'image'})
    identified = identify(both)
    assert identified.details['format'] == 'zip' and identified.details['contents'] == ['txt', 'xml']
    assert identified.details['txt_xml'] == 'identical (3 processes)'
    assert identify(zipped(tmp_path / 'xml-only.zip', {'a.xml': XML})).details['contents'] == ['xml']
    assert len(load_lxcat(tmp_path / 'xml-only.zip').processes) == 3
    with pytest.raises(IdentifyError, match='TXT and XML in the ZIP differ'):
        identify(zipped(tmp_path / 'differ.zip', {'a.txt': LXCAT, 'a.xml': XML.replace('3.000000e-20', '3.100000e-20')}))
    with pytest.raises(IdentifyError, match='without LXCat'):
        identify(zipped(tmp_path / 'other.zip', {'notes.txt': 'hello'}))
    with pytest.raises(IdentifyError, match='more than one'):
        identify(zipped(tmp_path / 'two.zip', {'a.txt': LXCAT, 'b.txt': LXCAT}))
    (tmp_path / 'download.xml').write_text(XML)
    assert identify(tmp_path / 'download.xml').details['format'] == 'xml'


def datasets_of(path: pathlib.Path) -> dict[str, tuple[bytes, dict[str, str]]]:
    """Data and attributes of every dataset, without the stored source file (which differs by design)"""
    found: dict[str, tuple[bytes, dict[str, str]]] = {}

    def visit(name: str, item: object) -> None:
        if isinstance(item, h5py.Dataset):
            found[name] = (item[()].tobytes(), {key: str(value) for key, value in item.attrs.items() if key != '* Source'})

    with h5py.File(path, 'r') as h5:
        h5.visititems(visit)
    return found


def test_builds_from_txt_xml_and_zip_are_identical(tmp_path: pathlib.Path) -> None:
    (tmp_path / 'a.txt').write_text(LXCAT)
    (tmp_path / 'a.xml').write_text(XML)
    zipped(tmp_path / 'a.zip', {'Cross section.txt': LXCAT, 'Cross section.xml': XML})
    contents = []
    for name in ('a.txt', 'a.xml', 'a.zip'):
        store = tmp_path / f'store-{name}'
        assert main(['import', str(tmp_path / name), '--store', str(store)]) == 0
        recipe = tmp_path / 'recipe.yaml'
        recipe.write_text(RECIPE.format(source='lxcat/test-a+test-b/ar'))
        output = tmp_path / f'{name}.h5'
        assert main(['build', str(recipe), '-o', str(output), '--store', str(store), '--offline']) == 0
        contents.append(datasets_of(output))
    assert len(contents[0]) == 3 and contents[0] == contents[1] == contents[2]  # same data and attributes, only the source file differs
    assert read_any(tmp_path / 'a.xml').summary()['cross-sections'] == 3  # plot/diff read XML and ZIP downloads directly
    assert read_any(tmp_path / 'a.zip').summary()['cross-sections'] == 3


def part(processes: str, generated: str = '01 Jun 2026') -> str:
    """LXCat file of database Test-A with some of its processes (as when only some processes are selected on LXCat)"""
    head = LXCAT.split('ELASTIC\n')[0].replace('01 Jun 2026', generated)
    blocks = {'elastic': 'ELASTIC\n' + LXCAT.split('ELASTIC\n')[1].split('IONIZATION\n')[0], 'ionization': 'IONIZATION\n' + LXCAT.split('IONIZATION\n')[1].split('xxxx')[0]}
    return head + ''.join(blocks[name] for name in processes.split('+'))


def test_growing_downloads(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = tmp_path / 'store'
    (tmp_path / 'first.txt').write_text(part('elastic'))
    (tmp_path / 'later.txt').write_text(part('ionization', '05 Jun 2026'))
    assert main(['import', str(tmp_path / 'first.txt'), '--store', str(store)]) == 0
    capsys.readouterr()
    assert main(['import', str(tmp_path / 'later.txt'), '--store', str(store)]) == 0
    assert '1 new process(es), 0 with a newer or other update time, 0 already in the store' in capsys.readouterr().out

    recipe = tmp_path / 'recipe.yaml'
    recipe.write_text('cross_sections:\n  - source: lxcat\n    database: Test-A\n    species: e / Ar\n    processes: [Elastic, Ionization]\n')
    output = tmp_path / 'grown.h5'
    assert main(['build', str(recipe), '-o', str(output), '--store', str(store), '--offline']) == 0
    database = read_database(output)
    assert sorted(xsec.kind.value for xsec in database.collision_pairs['Ar-electron'].cross_sections) == ['ELASTIC', 'REACTION']  # union
    assert '* piclas-db sources' in ''.join(h5py.File(output, 'r').attrs.keys())

    # the full download as well: the same processes again, taken once
    (tmp_path / 'full.txt').write_text(LXCAT.replace('01 Jun 2026', '10 Jun 2026'))
    capsys.readouterr()
    assert main(['import', str(tmp_path / 'full.txt'), '--store', str(store)]) == 0
    assert '1 new process(es)' in capsys.readouterr().out  # the Backscat of Test-B; Elastic and Ionization already there
    capsys.readouterr()
    assert main(['build', str(recipe), '-o', str(output), '--store', str(store), '--offline', '--force']) == 0
    assert 'in 2 downloads (identical), taken from' in capsys.readouterr().out

    # a newer update of a process replaces the older
    (tmp_path / 'update.txt').write_text(part('elastic', '20 Jun 2026').replace('2020-01-01 00:00:00', '2024-02-02 00:00:00').replace('2.0e-20', '2.5e-20'))
    assert main(['import', str(tmp_path / 'update.txt'), '--store', str(store)]) == 0
    capsys.readouterr()
    assert main(['build', str(recipe), '-o', str(output), '--store', str(store), '--offline', '--force']) == 0
    assert 'updated 2020-01-01 00:00:00 -> 2024-02-02 00:00:00' in capsys.readouterr().out
    elastic = next(x for x in read_database(output).collision_pairs['Ar-electron'].cross_sections if x.kind.value == 'ELASTIC')
    assert np.isclose(elastic.data[-1, 1], 2.5e-20)

    # the same process and update time with other data: conflict
    (tmp_path / 'conflict.txt').write_text(part('ionization', '25 Jun 2026').replace('3.0e-20', '3.3e-20'))
    assert main(['import', str(tmp_path / 'conflict.txt'), '--store', str(store)]) == 0
    capsys.readouterr()
    assert main(['build', str(recipe), '-o', str(output), '--store', str(store), '--offline', '--force']) == 1
    assert 'differs between downloads with the same update time' in capsys.readouterr().out

    # an expected process that was never downloaded
    recipe.write_text('cross_sections:\n  - source: lxcat\n    database: Test-A\n    species: e / Ar\n    processes: [Excitation]\n')
    assert main(['build', str(recipe), '-o', str(output), '--store', str(store), '--offline', '--force']) == 1
    assert "no process 'Excitation'" in capsys.readouterr().out
    recipe.write_text('cross_sections:\n  - source: lxcat\n    species: e / Ar\n')
    assert main(['build', str(recipe), '-o', str(output), '--store', str(store), '--offline', '--force']) == 1  # database required
    assert len(Store(store).entries()) == 5
