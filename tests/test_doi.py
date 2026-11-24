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
import urllib.parse
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

REAL_OPENALEX_SEARCH, REAL_GET_JSON, REAL_PDF_PAGES = doi_module.openalex_search, doi_module.get_json, doi_module.pdf_pages  # before the autouse fixture
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
    second = {**RECORDS['10.9999/test.2001.42'], 'DOI': '10.9999/test.2001.43'}  # another paper of the same author and year
    monkeypatch.setitem(RECORDS, '10.9999/test.2001.43', second)
    (tmp_path / 'a.pdf').write_bytes(PDF)
    (tmp_path / 'b.pdf').write_bytes(PDF.replace(b'2001.42', b'2001.43'))
    (tmp_path / 'c.pdf').write_bytes(PDF + b'% the first paper again, another download\n')
    assert main(['import', str(tmp_path / 'a.pdf'), str(tmp_path / 'b.pdf'), str(tmp_path / 'c.pdf'), '--literature']) == 0
    out = capsys.readouterr().out
    assert '✓ author-2001 ' in out and '! author-2001b ' in out and 'key author-2001 is taken' in out  # the suffix is to be checked
    assert '≈ author-2001 ' in out and 'same paper as author-2001 (DOI 10.9999/test.2001.42)' in out  # same DOI: not imported
    assert '3 paper(s): 1 fine, 1 to check, 0 failed, 1 same paper in another file' in out and '--literature author-2001 --new-version' in out
    assert main(['import', str(tmp_path / 'c.pdf'), '--literature', '--new-version']) == 0  # kept as a second file of author-2001
    assert len([e for e in Store(tmp_path / 'store').entries() if e.meta.get('dataset') == 'author-2001']) == 2
    capsys.readouterr()
    names = sorted(e.path.name for e in Store(tmp_path / 'store').entries())
    assert names[0].startswith('author-2001_') and names[1].startswith('author-2001_') and names[2].startswith('author-2001b_')
    assert doi_module.Citation(first_author='Gökçen', year=2007).key(set()) == 'goekcen-2007'  # umlaut spelled out, cedilla dropped
    assert doi_module.Citation(first_author='Müller', year=1990).key(set()) == 'mueller-1990'
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


def test_same_paper_by_text(tmp_path: pathlib.Path) -> None:
    """Without DOI: the text of the first pages, with tolerance for a cover page and watermarks"""
    from piclas_db.sources import same_paper  # noqa: PLC0415

    body = ' '.join(f'word{i} sentence about collision cross sections number {i}' for i in range(120))
    with_cover = 'Downloaded by SOME LIBRARY on 2 February 2015 terms and conditions apply ' * 5 + body
    other = ' '.join(f'unrelated{i} text on rate coefficients of reactions {i}' for i in range(120))
    a, b, c = (same_paper.shingles(text) for text in (body, with_cover, other))
    assert same_paper.containment(a, b) > 0.95 and same_paper.containment(a, c) < 0.05
    assert len(a) >= same_paper.MINIMUM


def test_review(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """--review: overview first, then paper by paper; skipped papers are remembered, quitting and continuing works"""
    from piclas_db.commands import paper_review  # noqa: PLC0415

    monkeypatch.setenv('PICLAS_DB_STORE', str(tmp_path / 'store'))
    monkeypatch.setattr(doi_module, 'pdf_text', lambda path, pages=2: TEXT if path.name.startswith('2001') else '')
    monkeypatch.setattr(doi_module, 'get_json', fake_get_json)
    monkeypatch.setattr('sys.stdin.isatty', lambda: True)
    opened: list[str] = []
    monkeypatch.setattr(paper_review, 'open_link', opened.append)
    (tmp_path / '2001-Author-Rate-Parameters.pdf').write_bytes(PDF)
    (tmp_path / '1995-Laux-Direkte-Simulation.pdf').write_bytes(PLAIN)
    (tmp_path / '1990-Other-Report.pdf').write_bytes(PLAIN + b'% other\n')
    monkeypatch.chdir(tmp_path)
    files = ['1990-Other-Report.pdf', '1995-Laux-Direkte-Simulation.pdf', '2001-Author-Rate-Parameters.pdf']

    answers = iter(['s', 'o', 'p', 'y', 'r M. Laux, Direkte Simulation, dissertation, Stuttgart 1995', 'k laux-1995', 'y', 'q'])
    monkeypatch.setattr('builtins.input', lambda prompt='': next(answers))
    assert main(['import', *files, '--literature', '--review', '--checklist', 'check.md']) == 0
    out = capsys.readouterr().out
    assert out.index('[3/3]') < out.index('Review: 3 paper(s) to decide')  # the overview (numbered blocks, table) comes first
    assert '# ' in out and 'DOI (found in) or reason' in out and 'Next steps' not in out
    assert 'imported -> literature/laux-1995/' in out and 'not importable yet' in out and 'Stopped: 1 paper(s) left' in out
    assert '- [ ] 3. ✓ `author-2001` 2001-Author-Rate-Parameters.pdf — https://doi.org/10.9999/test.2001.42' in (tmp_path / 'check.md').read_text()

    answers = iter(['o', 'y'])  # the same command again: Laux is stored (=), the report was skipped, only author-2001 is left
    assert main(['import', *files, '--literature', '--review']) == 0
    out = capsys.readouterr().out
    assert opened[0] == 'https://scholar.google.com/scholar?q=1995+Laux+Direkte+Simulation'  # no DOI: a search for the file name
    assert opened[1].endswith('/1995-Laux-Direkte-Simulation.pdf')  # the PDF in the desktop's viewer
    assert 'Review: 1 paper(s) to decide, 1 skipped earlier' in out and opened[2:] == ['https://doi.org/10.9999/test.2001.42']
    assert 'imported -> literature/author-2001/' in out and 'Review done: 1 imported, 0 skipped' in out
    assert sorted(e.meta['dataset'] for e in Store(tmp_path / 'store').entries()) == ['author-2001', 'laux-1995']
    monkeypatch.setattr('sys.stdin.isatty', lambda: False)
    assert main(['import', *files, '--literature', '--review']) == 1  # not in a terminal


LOFTHOUSE = """NONEQUILIBRIUM HYPERSONIC AEROTHERMODYNAMICS USING THE DIRECT SIMULATION MONTE CARLO AND NAVIER-STOKES MODELS
by Andrew J. Lofthouse
A dissertation submitted in partial fulfillment of the requirements for the degree of Doctor of Philosophy
(Aerospace Engineering) in The University of Michigan 2008
Doctoral Committee: Professor Iain D. Boyd, Chair
"""
BOYD = {
    'DOI': '10.2514/5.9781624103292.0045.0102',
    'title': ['Computation of Hypersonic Nonequilibrium Flows Using the Direct Simulation Monte Carlo Method'],
    'author': [{'given': 'Iain D.', 'family': 'Boyd'}],
    'issued': {'date-parts': [[2015]]},
}


def test_search_needs_whole_title_and_author(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Real false match: Lofthouse's dissertation and Boyd's chapter share 7 of 10 title words, and Boyd is on the page as chair"""
    path = tmp_path / 'thesis.pdf'
    path.write_bytes(PLAIN)
    monkeypatch.setattr(doi_module, 'pdf_text', lambda path, pages=2: LOFTHOUSE)
    monkeypatch.setattr(doi_module, 'get_json', lambda url, timeout: {'items': [BOYD]} if 'query.bibliographic' in url else None)
    assert doi_module.title_found(doi_module.record_title(BOYD), LOFTHOUSE) >= doi_module.TITLE_MATCH  # the old rule would take it
    cited = doi_module.paper_citation(path, None, None)
    assert cited.doi is None and cited.reference is None
    record = {'author': [{'family': 'Müller'}]}
    assert doi_module.author_found(record, 'H. Muller') and doi_module.author_found(record, 'H. MUELLER') and not doi_module.author_found(record, 'H. Miller')
    assert doi_module.ascii_fold('Mu\u0308ller MÜLLER Straße') == 'Mueller MUELLER Strasse'  # decomposed ü, all caps, ß


def test_review_dry_run(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """-n --review: decide now (y approves, nothing stored); the next --review imports the approved papers without asking"""
    monkeypatch.setenv('PICLAS_DB_STORE', str(tmp_path / 'store'))
    monkeypatch.setattr(doi_module, 'pdf_text', lambda path, pages=2: TEXT if path.name.startswith('2001') else '')
    monkeypatch.setattr(doi_module, 'get_json', fake_get_json)
    monkeypatch.setattr('sys.stdin.isatty', lambda: True)
    (tmp_path / '2001-Author-Rate-Parameters.pdf').write_bytes(PDF)
    (tmp_path / '1995-Laux-Direkte-Simulation.pdf').write_bytes(PLAIN)
    monkeypatch.chdir(tmp_path)
    files = ['1995-Laux-Direkte-Simulation.pdf', '2001-Author-Rate-Parameters.pdf']
    answers = iter(['r M. Laux, dissertation, Stuttgart 1995', 'k laux-1995', 'y', 'y'])
    monkeypatch.setattr('builtins.input', lambda prompt='': next(answers))
    assert main(['import', *files, '--literature', '-n', '--review']) == 0
    out = capsys.readouterr().out
    assert 'Review (dry run: y approves, nothing is stored): 2 paper(s) to decide' in out and out.count('approved as') == 2
    assert 'Review done: 2 approved' in out and not (tmp_path / 'store').exists()
    answers = iter([])  # nothing is asked: both were approved
    assert main(['import', *files, '--literature', '--review']) == 0
    out = capsys.readouterr().out
    assert 'Importing 2 paper(s) approved in an earlier dry-run review' in out and 'laux-1995: imported' in out and 'author-2001: imported' in out
    assert 'Review: 0 paper(s) to decide' in out
    stored = {e.meta['dataset']: e.meta for e in Store(tmp_path / 'store').entries()}
    assert sorted(stored) == ['author-2001', 'laux-1995'] and stored['laux-1995']['reference'] == 'M. Laux, dissertation, Stuttgart 1995'


def test_open_link_is_detached_and_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    from piclas_db.commands import paper_review  # noqa: PLC0415

    calls: list[tuple] = []
    monkeypatch.setattr(paper_review.sys, 'platform', 'linux')
    monkeypatch.setattr(paper_review.shutil, 'which', lambda name: '/usr/bin/xdg-open')
    monkeypatch.setattr(paper_review.subprocess, 'Popen', lambda command, **options: calls.append((command, options)))
    paper_review.open_link('https://doi.org/10.9999/x')
    command, options = calls[0]
    assert command == ['/usr/bin/xdg-open', 'https://doi.org/10.9999/x'] and options['start_new_session']
    assert options['stdout'] == options['stderr'] == paper_review.subprocess.DEVNULL  # no browser log lines in the review


JANEV_TEXT = """Collision Processes in Low-Temperature
Hydrogen Plasmas
R.K. Janev1,2, D. Reiter1, U. Samm1
1 Institut für Plasmaphysik, Forschungszentrum Jülich GmbH
Jül-4105
"""
JANEV_CHAPTER = {'DOI': '10.1007/978-3-642-71935-6_7', 'title': ['Collision Processes of H+'], 'author': [{'family': 'Janev'}], 'issued': {'date-parts': [[1987]]}}
JANEV_WORK = {
    'doi': None,
    'display_name': 'Collision Processes in Low-Temperature Hydrogen Plasmas',
    'publication_year': 2003,
    'authorships': [{'author': {'display_name': 'R. K. Janev'}}],
}


def test_title_and_author_checks() -> None:
    assert doi_module.title_in_text('Modeling of nonequilibrium CO Fourth-Positive and CN Violet emission', 'Modeling of nonequilibrium CO Fourth-Posi-\ntive and CN Violet emission in')
    assert doi_module.title_in_text(doi_module.tidy_title('emission in CO<sub>2</sub>–N<sub>2</sub> gases'), 'emission in CO 2 -N 2 gases')
    assert doi_module.title_in_text('Forschungszentrum Jülich report', 'FORSCHUNGSZENTRUM JULICH REPORT')
    assert not doi_module.title_in_text('Processes Collision in Plasmas', JANEV_TEXT)  # same words, other order
    assert not doi_module.title_in_text('Collision Processes of H+', JANEV_TEXT)  # the chapter title is not on the report's page
    assert doi_module.author_found({'author': [{'family': 'Janev'}]}, JANEV_TEXT)  # Janev1,2
    record = {'author': [{'family': 'Müller'}]}
    assert all(doi_module.author_found(record, text) for text in ('H. Mueller', 'H. Muller', 'H. MÜLLER')) and not doi_module.author_found({}, 'H. Mueller')
    assert doi_module.title_lines(JANEV_TEXT) == 'Collision Processes in Low-Temperature Hydrogen Plasmas'
    assert doi_module.title_lines(LOFTHOUSE).startswith('NONEQUILIBRIUM HYPERSONIC AEROTHERMODYNAMICS')
    assert doi_module.title_lines('A Title\nSecond line\nabstract: text') == 'A Title Second line'
    assert doi_module.title_lines('Title\nname@example.org') == 'Title' and doi_module.title_lines('Title\nUniversity of Stuttgart') == 'Title'


def test_crossref_search_rejects_similar_chapter(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Janev's report and his chapter "Collision Processes of H+": both long words of the chapter title are on the page"""
    path = tmp_path / 'report.pdf'
    path.write_bytes(PLAIN)
    monkeypatch.setattr(doi_module, 'pdf_text', lambda path, pages=2: JANEV_TEXT)
    monkeypatch.setattr(doi_module, 'get_json', lambda url, timeout: {'items': [JANEV_CHAPTER]} if 'query.bibliographic' in url else None)
    assert doi_module.paper_citation(path, None, None).doi is None
    right = {**JANEV_CHAPTER, 'DOI': '10.9999/report', 'title': ['Collision Processes in Low-Temperature Hydrogen Plasmas']}
    monkeypatch.setattr(doi_module, 'get_json', lambda url, timeout: {'items': [JANEV_CHAPTER, right]} if 'query.bibliographic' in url else None)
    assert doi_module.paper_citation(path, None, None).doi == '10.9999/report'  # the right hit among the others


def test_openalex_fallback(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A report without DOI: not at Crossref, found at OpenAlex by its title; the query has only the title words"""
    monkeypatch.setattr(doi_module, 'openalex_search', REAL_OPENALEX_SEARCH)  # replaced by the autouse fixture; here fetch_json is replaced
    monkeypatch.setattr(doi_module, 'get_json', REAL_GET_JSON)
    monkeypatch.setenv('PICLAS_DB_USER_NAME', 'Tester')
    monkeypatch.setenv('PICLAS_DB_USER_EMAIL', 'tester@example.org')
    monkeypatch.setenv('OPENALEX_API_KEY', 'KEY123')
    path = tmp_path / 'report.pdf'
    path.write_bytes(PLAIN)
    monkeypatch.setattr(doi_module, 'pdf_text', lambda path, pages=2: JANEV_TEXT)
    asked: list[str] = []

    def fetch(url: str, timeout: float, service: str = 'Crossref') -> Optional[dict]:
        asked.append(url)
        if service == 'OpenAlex':
            return {'results': [{**JANEV_WORK, 'display_name': 'Another Report'}, JANEV_WORK]}
        return {'message': {'items': [JANEV_CHAPTER]}} if 'query.bibliographic' in url else None

    monkeypatch.setattr(doi_module, 'fetch_json', fetch)
    cited = doi_module.paper_citation(path, None, None)
    assert (cited.doi, cited.reference_from, cited.key(set())) == (None, 'openalex', 'janev-2003')
    assert cited.reference == 'Janev, Collision Processes in Low-Temperature Hydrogen Plasmas, 2003' and 'found by searching OpenAlex' in cited.notes[-1]
    query = urllib.parse.parse_qs(urllib.parse.urlparse(asked[-1]).query)
    assert query['search'] == ['Collision Processes in Low Temperature Hydrogen Plasmas'] and query['mailto'] == ['tester@example.org'] and query['api_key'] == ['KEY123']

    def too_many(url: str, timeout: float, service: str = 'Crossref') -> Optional[dict]:
        if service == 'OpenAlex':
            raise doi_module.Unreachable('OpenAlex: HTTP 429 (too many requests)')
        return None

    monkeypatch.setattr(doi_module, 'fetch_json', too_many)
    cited = doi_module.paper_citation(path, None, None)
    assert cited.doi is None and cited.reference is None and 'OpenAlex: HTTP 429' in cited.notes[-1]  # reported, not offline
    other = {**JANEV_WORK, 'authorships': [{'author': {'display_name': 'A. Nobody'}}]}
    monkeypatch.setattr(doi_module, 'fetch_json', lambda url, timeout, service='Crossref': {'results': [other]} if service == 'OpenAlex' else None)
    assert doi_module.paper_citation(path, None, None).reference is None  # other first author: rejected


def test_from_openalex_authors() -> None:
    names = {'R. K. Janev': 'Janev', 'Janev, R. K.': 'Janev', 'John Smith Jr.': 'Smith', 'Hans von der Heydt': 'Heydt'}
    for name, family in names.items():
        record = doi_module.from_openalex({'display_name': 'T', 'authorships': [{'author': {'display_name': name}}]})
        assert record is not None and record['author'] == [{'family': family}]
    assert doi_module.from_openalex({'display_name': ''}) is None
    assert doi_module.from_openalex({'display_name': 'T', 'doi': 'https://doi.org/10.1/X'}) == {'title': ['T'], 'DOI': '10.1/X'}


def test_pdfminer_warnings_are_silenced(tmp_path: pathlib.Path) -> None:
    """Warnings of pdfminer about incomplete fonts of older PDFs must not appear on the terminal (through the progress bar)"""
    import logging  # noqa: PLC0415

    logging.getLogger('pdfminer').setLevel(logging.WARNING)
    (tmp_path / 'paper.pdf').write_bytes(PLAIN)
    doi_module.plumber_text(tmp_path / 'paper.pdf', 1)
    assert logging.getLogger('pdfminer').getEffectiveLevel() == logging.ERROR


def test_year_of_the_printed_issue() -> None:
    """Park et al. 2001 (J. Thermophys. Heat Transfer 15(1), January 2001) was online in 2000: the key must say 2001"""
    record = {'issued': {'date-parts': [[2000, 12]]}, 'published-online': {'date-parts': [[2000, 12]]}, 'published-print': {'date-parts': [[2001, 1]]}}
    assert doi_module.record_year(record) == 2001
    assert doi_module.record_year({'issued': {'date-parts': [[2014, 9]]}}) == 2014


PARK_TEXT = """JOURNAL OF THERMOPHYSICS AND HEAT TRANSFER
Vol. 15, No. 1, January– March 2001
Chemical-Kinetic Parameters of Hyperbolic Earth Entry
Chul Park¤
Eloret Corporation, Moffett Field, California 94085
and
Richard L. Jaffe† and Harry Partridge‡
NASA Ames Research Center, Moffett Field, California 94035
"""
PARK = {
    'DOI': '10.2514/2.6582',
    'title': ['Chemical-Kinetic Parameters of Hyperbolic Earth Entry'],
    'author': [{'given': 'Chul', 'family': 'Park'}],
    'container-title': ['Journal of Thermophysics and Heat Transfer'],
    'issued': {'date-parts': [[2000, 12]]},
    'published-online': {'date-parts': [[2000, 12]]},
    'published-print': {'date-parts': [[2001, 1]]},
}
PARK_CONFERENCE = {
    'DOI': '10.2514/6.2000-210',
    'title': ['Chemical-kinetic parameters of hyperbolic earth entry'],
    'author': [{'family': 'Park'}],
    'container-title': ['38th Aerospace Sciences Meeting and Exhibit'],
    'issued': {'date-parts': [[2000, 1, 10]]},
}


def test_journal_before_conference_version(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Park et al. 2001 and the AIAA paper 2000-210 share title and first author; journal and year on the page decide"""
    assert doi_module.evidence(PARK, PARK_TEXT) == (True, True)
    assert doi_module.evidence(PARK_CONFERENCE, PARK_TEXT) == (False, False) and doi_module.evidence({}, PARK_TEXT) == (False, False)
    without_journal = {key: value for key, value in PARK.items() if key != 'container-title'}
    first = {**PARK_CONFERENCE, 'DOI': '10.9999/first', 'container-title': []}
    second = {**PARK_CONFERENCE, 'DOI': '10.9999/second', 'container-title': []}
    choices = {
        '10.2514/2.6582': [PARK_CONFERENCE, PARK],
        '10.2514/2.6582 ': [PARK_CONFERENCE, without_journal],  # the year 2001 alone decides
        '10.2514/6.2000-210': [PARK_CONFERENCE],  # only the conference version: taken, nothing speaks against it
        '10.9999/first': [first, second],  # equal evidence: the search order
    }
    for expected, hits in choices.items():
        hit = doi_module.best_hit(hits, PARK_TEXT)
        assert hit is not None and hit['DOI'] == expected.strip()
    path = tmp_path / 'park.pdf'
    path.write_bytes(PLAIN)
    monkeypatch.setattr(doi_module, 'pdf_text', lambda path, pages=2: PARK_TEXT)
    monkeypatch.setattr(doi_module, 'get_json', lambda url, timeout: {'items': [PARK_CONFERENCE, PARK]} if 'query.bibliographic' in url else None)
    cited = doi_module.paper_citation(path, None, None)  # whole path: no DOI on the page, Crossref search
    assert (cited.doi, cited.key(set())) == ('10.2514/2.6582', 'park-2001')


MAN_TEXT = """J. Phys. B: At. Mol. Phys. 20 (1987) 5865-5880. Printed in the UK

A measurement of the cross section for electron impact
ionisation of Ne', AI+, Kr' and Xe'
K F Man?, A C H Smith? and M F A Harrison$
t Department of Physics and Astronomy, University College London, London W C l E 6BT,
UK"""
SUP = '\n                    <sup>+</sup>\n                    '
MAN = {
    'DOI': '10.1088/0022-3700/20/21/030',
    'title': [f'A measurement of the cross section for electron impact ionisation of Ne{SUP}, Ar{SUP}, Kr{SUP}and Xe{SUP}'],
    'author': [{'family': 'Man'}],
    'container-title': ['Journal of Physics B: Atomic and Molecular Physics'],
    'short-container-title': ['J. Phys. B: At. Mol. Phys.'],
    'issued': {'date-parts': [[1987, 11, 14]]},
}
MAN_SERIES = {**MAN, 'DOI': '10.1088/0022-3700/20/6/019', 'title': ['A measurement of the cross section for ionisation of He+, Ne+ and Ar+']}  # invented
MAN_TWIN = {**MAN, 'DOI': '10.1088/0022-3700/99/1/001', 'title': ['A measurement of the cross section for electron impact ionisation of Ne+, Ar+, Kr+ and Xe2+']}  # invented


def test_tolerant_title_check() -> None:
    """Old scans with an OCR text layer: up to 5 % of a long title may differ ('Ar+' read as 'AI+'); short titles exactly"""
    edits = doi_module.edits
    assert (edits('abc', 'xxabcxx'), edits('abc', 'xxabxx'), edits('abc', 'xxaxcxx'), edits('abc', 'xxabbcxx'), edits('abc', ''), edits('', 'abc')) == (0, 1, 1, 1, 3, 0)
    title = doi_module.record_title(MAN)
    assert doi_module.title_errors(title, MAN_TEXT) == 1 and doi_module.title_in_text(title, MAN_TEXT) and doi_module.title_share(title, MAN_TEXT) == 98
    assert not doi_module.title_in_text('Collision Processes of H', JANEV_TEXT)  # 21 characters: no difference allowed
    assert not doi_module.title_in_text('Abcdefghijklmnop', 'xx Abcdefghijklmnoq xx')  # 16 characters, 1 differs
    assert doi_module.title_in_text('Abcdefghijklmnopqrstuvwxyzab', 'xx Abcdefghijklmnopqrstuvwxyzac xx')  # 28 characters, 1 differs
    assert doi_module.evidence(MAN, MAN_TEXT) == (True, True)  # the journal as abbreviated on the page


def test_series_and_twin(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert not doi_module.search_hit(MAN_SERIES, MAN_TEXT, MAN_TEXT) and doi_module.title_share(doi_module.record_title(MAN_SERIES), MAN_TEXT) == 67
    for hits in ([MAN_SERIES, MAN], [MAN_TWIN, MAN]):  # the twin differs in 2 characters, Man et al. 1987 in 1
        fitting = [record for record in hits if doi_module.search_hit(record, MAN_TEXT, MAN_TEXT)]
        hit = doi_module.best_hit(fitting, MAN_TEXT)
        assert hit is not None and hit['DOI'] == MAN['DOI']
    path = tmp_path / 'man.pdf'
    path.write_bytes(PLAIN)
    monkeypatch.setattr(doi_module, 'pdf_text', lambda path, pages=2: MAN_TEXT)
    monkeypatch.setattr(doi_module, 'get_json', lambda url, timeout: {'items': [MAN_SERIES, MAN_TWIN, MAN]} if 'query.bibliographic' in url else None)
    cited = doi_module.paper_citation(path, None, None)  # whole path: no DOI on the page, Crossref search
    assert (cited.doi, cited.key(set())) == (MAN['DOI'], 'man-1987')
    monkeypatch.setattr(doi_module, 'get_json', lambda url, timeout: {'items': [MAN_SERIES]} if 'query.bibliographic' in url else None)
    cited = doi_module.paper_citation(path, None, None)  # only the sibling: rejected, the closest hit named in the notes
    assert cited.doi is None and any('10.1088/0022-3700/20/6/019 (67 % of its title on the page) not taken' in note for note in cited.notes)


HUBER_TEXT = """MOLECULAR SPECTRA
and
MOLECULAR STRUCTURE
IV. CONSTANTS OF DIATOMIC
MOLECULES
By
K. P. Huber and G. Herzberg
National Research Council of Canada
VAN NOSTRAND REINHOLD COMPANY
NEW YORK CINCINNATI ATLANTA DALLAS SAN FRANCISCO"""
HUBER_BOOK = {'DOI': '10.1007/978-1-4757-0961-2', 'title': ['Molecular Spectra and Molecular Structure'], 'author': [{'family': 'Huber'}], 'issued': {'date-parts': [[1979]]}}
HUBER_CHAPTER = {
    'DOI': '10.1007/978-1-4757-0961-2_2',
    'title': ['Constants of diatomic molecules'],
    'author': [{'family': 'Huber'}],
    'container-title': ['Molecular Spectra and Molecular Structure'],
    'page': '8-689',
    'issued': {'date-parts': [[1979]]},
}
HUBER_ABBREVIATIONS = {**HUBER_CHAPTER, 'DOI': '10.1007/978-1-4757-0961-2_1', 'title': ['Abbreviated Publication Titles'], 'page': '1-7'}


def test_page_count_in_the_ranking() -> None:
    """The whole book against its chapter (Huber and Herzberg 1979), an article against its conference version (Park et al. 2001)"""
    hits = [HUBER_CHAPTER, HUBER_BOOK, HUBER_ABBREVIATIONS]
    fitting = [record for record in hits if doi_module.search_hit(record, HUBER_TEXT, HUBER_TEXT)]
    assert HUBER_ABBREVIATIONS not in fitting
    expected = {731: HUBER_BOOK['DOI'], 682: HUBER_CHAPTER['DOI'], 684: HUBER_CHAPTER['DOI'], None: HUBER_CHAPTER['DOI']}
    for pages, doi in expected.items():
        hit = doi_module.best_hit(fitting, HUBER_TEXT, pages=pages)
        assert hit is not None and hit['DOI'] == doi, pages
    journal = {'DOI': '10.2514/2.6582', 'title': PARK['title'], 'author': PARK['author'], 'page': '76-90'}  # no journal name, no dates
    hit = doi_module.best_hit([PARK_CONFERENCE, journal], PARK_TEXT, pages=15)
    assert hit is not None and hit['DOI'] == '10.2514/2.6582'
    ranges = {'8-689': 682, '76\u201390': 15, ' 5865 - 5880 ': 16, '123': None, 'e123': None, '90-76': None, '': None}
    assert {text: doi_module.page_range({'page': text}) for text in ranges} == ranges
    fits = {15: 1, 14: 1, 18: 1, 19: -1, 13: -1, None: 0}
    assert {pages: doi_module.page_fit({'page': '76-90'}, pages) for pages in fits} == fits and doi_module.page_fit({}, 15) == 0


def test_pdf_pages(tmp_path: pathlib.Path) -> None:
    """Page count of a real PDF (three pages)"""
    import shutil  # noqa: PLC0415

    import matplotlib  # noqa: PLC0415

    matplotlib.use('Agg')
    import matplotlib.pyplot as plt  # noqa: PLC0415
    from matplotlib.backends.backend_pdf import PdfPages  # noqa: PLC0415

    if shutil.which('pdfinfo') is None:
        pytest.skip('pdfinfo not installed')
    path = tmp_path / 'three.pdf'
    with PdfPages(path) as pdf:
        for _ in range(3):
            pdf.savefig(plt.figure())
    plt.close('all')
    assert REAL_PDF_PAGES(path) == 3 and REAL_PDF_PAGES(tmp_path / 'missing.pdf') is None
