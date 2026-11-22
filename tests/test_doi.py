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
"""DOI and citation of papers for import --literature (Crossref replaced by invented records; no network)"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import pathlib
from typing import Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import pytest

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.piclas_db import main
from piclas_db.sources import doi as doi_module
from piclas_db.store import Store
# ==================================================================================================================================

PDF = b'%PDF-1.4\n1 0 obj << /Type /Catalog /Metadata 2 0 R >> endobj\n2 0 obj << /Type /Metadata >>\nstream\n<x:xmpmeta><prism:doi>10.9999/test.2001.42</prism:doi></x:xmpmeta>\nendstream\nendobj\ntrailer << /Root 1 0 R >>\n%%EOF\n'
PLAIN = b'%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n'
TEXT = 'Journal of Invented Results 12 (2001)\nRate Parameters for Imaginary Plasmas\nA. Author and B. Other\n'
RECORDS = {
    '10.9999/test.2001.42': {
        'DOI': '10.9999/test.2001.42',
        'title': ['Rate parameters for imaginary plasmas'],
        'author': [{'given': 'Anna', 'family': 'Author'}, {'given': 'Bert J.', 'family': 'Other'}],
        'short-container-title': ['J. Invent. Res.'],
        'volume': '12',
        'issue': '3',
        'page': '100-110',
        'issued': {'date-parts': [[2001, 5]]},
    },
    '10.8888/0000-0000/1/2/3': {'DOI': '10.8888/0000-0000/1/2/3', 'title': ['Something entirely different about optics'], 'issued': {'date-parts': [[1925]]}},
}


def fake_get_json(url: str, timeout: float) -> Optional[dict]:
    if 'query.bibliographic' in url:
        return {'items': [RECORDS['10.9999/test.2001.42']]}
    return RECORDS.get(url.removeprefix(doi_module.CROSSREF))


def offline(url: str, timeout: float) -> Optional[dict]:
    raise doi_module.Unreachable('Crossref not reachable: test')


def test_file_names() -> None:
    names = {
        '0953-4075_2F21_2F6_2F014.pdf': ['10.1088/0953-4075/21/6/014'],
        'PhysRevA_6_1507.pdf': ['10.1103/PhysRevA.6.1507'],
        '6_2007-4543.pdf': ['10.2514/6.2007-4543'],
        '1_872535.pdf': ['10.2514/1.872535', '10.1063/1.872535'],
        'adnd_1997_0732.pdf': ['10.1006/adnd.1997.0732'],
        '10.9999%2Fabc.pdf': ['10.9999/abc'],
        'Johnston2014.pdf': [],
    }
    assert {name: doi_module.from_file_name(name) for name in names} == names
    assert doi_module.clean('https://doi.org/10.1016/j.x.2014.08.025.') == '10.1016/j.x.2014.08.025'


def test_citation_from_metadata(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / 'paper.pdf').write_bytes(PDF)
    monkeypatch.setattr(doi_module, 'pdf_text', lambda path, pages=2: TEXT)
    monkeypatch.setattr(doi_module, 'get_json', fake_get_json)
    cited = doi_module.paper_citation(tmp_path / 'paper.pdf', None, None)
    assert (cited.doi, cited.doi_found_in, cited.reference_from) == ('10.9999/test.2001.42', 'metadata', 'crossref')
    assert cited.reference == 'A. Author, B. J. Other, Rate parameters for imaginary plasmas, J. Invent. Res. 12(3):100-110, 2001'
    assert cited.link == 'https://doi.org/10.9999/test.2001.42' and not cited.notes
    monkeypatch.setattr(doi_module, 'get_json', offline)  # offline: the DOI of the PDF is taken unchecked
    cited = doi_module.paper_citation(tmp_path / 'paper.pdf', None, None)
    assert cited.doi == '10.9999/test.2001.42' and cited.reference is None and 'check the DOI at the link' in cited.notes


def test_wrong_article_in_download(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The file name gives a DOI whose title is not in the PDF: rejected, the PDF's first lines are searched instead"""
    path = tmp_path / '0000-0000_2F1_2F2_2F3.pdf'
    path.write_bytes(PLAIN)
    monkeypatch.setattr(doi_module, 'pdf_text', lambda path, pages=2: TEXT)
    monkeypatch.setattr(doi_module, 'get_json', lambda url, timeout: fake_get_json(url.replace('10.1088', '10.8888'), timeout))
    cited = doi_module.paper_citation(path, None, None)
    assert (cited.doi, cited.doi_found_in) == ('10.9999/test.2001.42', 'Crossref search')
    assert any('not on the first pages' in note for note in cited.notes)
    given = doi_module.paper_citation(path, '10.8888/0000-0000/1/2/3', 'given citation')  # a given DOI is kept, with a warning
    assert given.doi == '10.8888/0000-0000/1/2/3' and given.reference == 'given citation' and 'another article' in given.notes[0]
    unknown = doi_module.paper_citation(path, '10.0000/unknown', 'given citation')  # also when Crossref does not know it
    assert (unknown.doi, unknown.doi_found_in) == ('10.0000/unknown', 'given') and 'not known at Crossref' in unknown.notes[0]


def test_import_literature(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv('PICLAS_DB_STORE', str(tmp_path / 'store'))
    monkeypatch.setattr(doi_module, 'pdf_text', lambda path, pages=2: TEXT)
    monkeypatch.setattr(doi_module, 'get_json', fake_get_json)
    (tmp_path / 'paper.pdf').write_bytes(PDF)
    assert main(['import', str(tmp_path / 'paper.pdf'), '--literature', 'author-2001']) == 0
    out = capsys.readouterr().out
    assert '✓ author-2001' in out and 'https://doi.org/10.9999/test.2001.42' in out and 'cite  A. Author' in out
    assert '1 paper(s): 1 fine, 0 to check, 0 failed' in out and 'piclas-db literature list' in out
    paper = next(e for e in Store(tmp_path / 'store').entries() if e.meta.get('provider') == 'literature')
    assert paper.meta['doi'] == '10.9999/test.2001.42' and paper.meta['doi_found_in'] == 'metadata' and paper.meta['reference_from'] == 'crossref'
    for extra in ([], ['--dry-run']):  # the same file again, without key: recognized as already stored (no lookup, no error)
        assert main(['import', str(tmp_path / 'paper.pdf'), '--literature', *extra]) == 0
        out = capsys.readouterr().out
        assert '= author-2001' in out and 'already in the store: literature/author-2001/' in out and '0 failed, 1 already in the store' in out
    (tmp_path / 'other.pdf').write_bytes(PLAIN)
    monkeypatch.setattr(doi_module, 'pdf_text', lambda path, pages=2: '')
    monkeypatch.setattr(doi_module, 'get_json', offline)
    assert main(['import', str(tmp_path / 'other.pdf'), '--literature', 'other']) == 1
    out = capsys.readouterr().out
    assert '✗ —' in out and 'DOI and citation not found: give --doi or --reference' in out
    assert 'piclas-db import' in out and '--literature KEY --doi DOI' in out  # next step for the failed paper


def test_import_key_from_citation(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """--literature without KEY: first author and year; a taken key gets b; the stored file is named by the key"""
    monkeypatch.setenv('PICLAS_DB_STORE', str(tmp_path / 'store'))
    monkeypatch.setattr(doi_module, 'pdf_text', lambda path, pages=2: TEXT)
    monkeypatch.setattr(doi_module, 'get_json', fake_get_json)
    (tmp_path / 'a.pdf').write_bytes(PDF)
    (tmp_path / 'b.pdf').write_bytes(PDF + b'% another copy\n')
    assert main(['import', str(tmp_path / 'a.pdf'), str(tmp_path / 'b.pdf'), '--literature']) == 0
    out = capsys.readouterr().out
    assert '✓ author-2001 ' in out and '! author-2001b ' in out and 'key author-2001 is taken' in out  # the suffix is to be checked
    assert '2 paper(s): 1 fine, 1 to check, 0 failed' in out
    names = sorted(e.path.name for e in Store(tmp_path / 'store').entries())
    assert names[0].startswith('author-2001_') and names[1].startswith('author-2001b_')
    assert doi_module.Citation(first_author='Gökçen', year=2007).key(set()) == 'gokcen-2007'
    (tmp_path / 'c.pdf').write_bytes(PLAIN)
    monkeypatch.setattr(doi_module, 'get_json', offline)
    monkeypatch.setattr(doi_module, 'pdf_text', lambda path, pages=2: '')
    assert main(['import', str(tmp_path / 'c.pdf'), '--literature', '--doi', '10.1/x']) == 1
    assert 'no key: first author and year unknown' in capsys.readouterr().out


def test_tidy_title() -> None:
    assert doi_module.tidy_title('Emission in CO 2 –N 2 gases') == 'Emission in CO2–N2 gases'
    assert doi_module.tidy_title('Diffusion in CO<sub>2</sub>/N<sub>2</sub> Mixtures') == 'Diffusion in CO2/N2 Mixtures'
    assert doi_module.tidy_title('Part 2: results of Table 3') == 'Part 2: results of Table 3'


def test_several_papers_need_automatic_keys(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv('PICLAS_DB_STORE', str(tmp_path / 'store'))
    (tmp_path / 'a.pdf').write_bytes(PDF)
    (tmp_path / 'b.pdf').write_bytes(PLAIN)
    assert main(['import', str(tmp_path / 'a.pdf'), str(tmp_path / 'b.pdf'), '--literature', 'one-2001']) == 1
    assert main(['import', str(tmp_path / 'a.pdf'), str(tmp_path / 'b.pdf'), '--literature', '--doi', '10.1/x']) == 1
    assert capsys.readouterr().out.count('are for one paper') == 2


def test_dry_run_report_and_next_steps(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """dry run of several papers: a block per paper, the summary and the commands of the next steps"""
    from piclas_db.commands.paper_report import suggested_key  # noqa: PLC0415

    monkeypatch.setenv('PICLAS_DB_STORE', str(tmp_path / 'store'))
    monkeypatch.setattr(doi_module, 'pdf_text', lambda path, pages=2: TEXT if path.name.startswith('2001') else '')
    monkeypatch.setattr(doi_module, 'get_json', fake_get_json)
    (tmp_path / '2001-Author-Rate-Parameters.pdf').write_bytes(PDF)
    (tmp_path / '1995-Laux-Direkte-Simulation.pdf').write_bytes(PLAIN)
    monkeypatch.chdir(tmp_path)
    assert main(['import', '2001-Author-Rate-Parameters.pdf', '1995-Laux-Direkte-Simulation.pdf', '--literature', '--dry-run']) == 1
    out = capsys.readouterr().out
    assert '✓ author-2001' in out and '✗ —                    1995-Laux-Direkte-Simulation.pdf' in out
    assert '2 paper(s): 1 fine, 0 to check, 1 failed (dry run: nothing copied)' in out
    assert 'piclas-db import 1995-Laux-Direkte-Simulation.pdf --literature laux-1995 --doi DOI' in out
    assert 'Import the 1 paper(s) found' in out and '2001-Author-Rate-Parameters.pdf' in out.split('Import the 1 paper(s) found')[1]
    assert not (tmp_path / 'store').exists()
    assert suggested_key('1997-Bourdon-Study.pdf') == 'bourdon-1997' and suggested_key('cr500501m.pdf') == 'KEY'
