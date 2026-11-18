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
import pytest
import yaml

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db import config
from piclas_db.piclas_db import main
from piclas_db.resolve import mirror_url
from piclas_db.store import Store, default_store
from tests.test_literature import PDF
# ==================================================================================================================================


def write_config(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, content: dict) -> pathlib.Path:
    path = tmp_path / 'config.yaml'
    path.write_text(yaml.safe_dump(content))
    monkeypatch.setenv('PICLAS_DB_CONFIG', str(path))
    return path


def test_store_and_mirror(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'xdg'))
    assert default_store() == tmp_path / 'xdg' / 'piclas-db' / 'store'  # no configuration
    write_config(tmp_path, monkeypatch, {'store': str(tmp_path / 'configured'), 'mirror': 'git@example.org:org/sources.git'})
    assert default_store() == tmp_path / 'configured'
    assert mirror_url(None, Store(tmp_path / 'configured')) == 'git@example.org:org/sources.git'
    monkeypatch.setenv('PICLAS_DB_STORE', str(tmp_path / 'environment'))  # environment before configuration
    monkeypatch.setenv('PICLAS_DB_MIRROR', 'git@example.org:org/env.git')
    assert default_store() == tmp_path / 'environment'
    assert mirror_url(None, Store(tmp_path / 'x')) == 'git@example.org:org/env.git'
    assert mirror_url('git@example.org:org/cli.git', Store(tmp_path / 'x')) == 'git@example.org:org/cli.git'  # command line first


def test_command_defaults(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    write_config(tmp_path, monkeypatch, {'store': str(tmp_path / 'store'), 'literature': {'reviewer': 'Configured Reviewer'}, 'extract': {'by': 'Configured Person'}})
    (tmp_path / 'paper.pdf').write_bytes(PDF)
    assert main(['import', str(tmp_path / 'paper.pdf'), '--literature', 'test-2008', '--doi', '10.0000/test']) == 0  # into the configured store
    assert (tmp_path / 'store' / 'literature' / 'test-2008').is_dir()
    work = tmp_path / 'work'
    assert main(['literature', 'template', 'test-2008', 'data', '--page', '1', '--table', '1', '-o', str(work)]) == 0
    (work / 'data.csv').write_text((work / 'data.csv').read_text() + '1,2\n2,3\n')
    assert main(['literature', 'add', str(work / 'data.extraction.yaml')]) == 0
    assert main(['literature', 'review', 'test-2008/data', '--approve']) == 0  # reviewer from the configuration
    capsys.readouterr()
    assert main(['literature', 'list']) == 0
    assert 'review approved' in capsys.readouterr().out
    entry = next(e for e in Store(tmp_path / 'store').entries() if e.meta['kind'] == 'extraction')
    assert entry.meta['extraction']['review']['reviewer'] == 'Configured Reviewer'
    assert main(['literature', 'review', 'test-2008/data', '--reject', '--reviewer', 'Command Line']) == 0  # command line first
    entry = next(e for e in Store(tmp_path / 'store').entries() if e.meta['kind'] == 'extraction')
    assert entry.meta['extraction']['review']['reviewer'] == 'Command Line'


def test_warnings_errors_and_command(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_config(tmp_path, monkeypatch, {'store': str(tmp_path / 'store'), 'unknown': 1, 'store-list': 2, 'check': {'colour': 'red'}})
    assert main(['check', str(tmp_path / 'missing.h5')]) == 1
    errors = capsys.readouterr().err
    assert "unknown entry 'unknown'" in errors and "unknown option 'colour'" in errors
    path.write_text('reservoir: [1, 2]\n')
    assert main(['reservoir', '--evaluate', str(tmp_path)]) == 1
    assert 'must be a mapping' in capsys.readouterr().err
    path.write_text('- a list\n')
    assert main(['check', str(tmp_path / 'missing.h5')]) == 1
    assert 'is a mapping' in capsys.readouterr().out
    path.write_text('store: [unclosed\n')
    with pytest.raises(config.ConfigError):
        config.load()

    new = tmp_path / 'sub' / 'config.yaml'
    monkeypatch.setenv('PICLAS_DB_CONFIG', str(new))
    assert main(['config']) == 0
    assert 'not present' in capsys.readouterr().out
    assert main(['config', '--init']) == 0
    assert new.read_text() == config.TEMPLATE and not config.load()  # template: everything commented out
    assert main(['config', '--init']) == 1  # exists
    new.write_text(yaml.safe_dump({'store': str(tmp_path / 's'), 'mirror': 'git@x:y.git', 'extract': {'by': 'Name'}}))
    capsys.readouterr()
    assert main(['config']) == 0
    out = capsys.readouterr().out
    assert '[configuration]' in out and 'by: Name' in out


def test_identity(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv('PICLAS_DB_USER_NAME')
    monkeypatch.delenv('PICLAS_DB_USER_EMAIL')
    monkeypatch.setenv('PICLAS_DB_CONFIG', str(tmp_path / 'config.yaml'))
    (tmp_path / 'paper.pdf').write_bytes(PDF)
    store = str(tmp_path / 'store')
    arguments = ['import', str(tmp_path / 'paper.pdf'), '--literature', 'test-2008', '--doi', '10.0000/test', '--store', store]
    assert main(arguments) == 1  # who imports? like git: name and email first
    assert 'piclas-db config --set user.name' in capsys.readouterr().out
    assert main([*arguments, '--dry-run']) == 0  # a dry run adds nothing

    assert main(['config', '--set', 'user.email', 'not-an-address']) == 1
    assert main(['config', '--set', 'user.phone', '123']) == 1
    assert main(['config', '--set', 'a.b.c', 'x']) == 1
    assert main(['config', '--set', 'user.name', 'Ada Lovelace']) == 0
    assert main(['config', '--set', 'user.email', 'ada@example.org']) == 0
    assert config.require_identity() == 'Ada Lovelace <ada@example.org>'
    capsys.readouterr()
    assert main(['config']) == 0
    assert 'Ada Lovelace <ada@example.org>' in capsys.readouterr().out

    assert main(arguments) == 0
    paper = Store(store).entries()[0]
    assert paper.meta['imported_by'] == 'Ada Lovelace <ada@example.org>'
    work = tmp_path / 'work'
    assert main(['literature', 'template', 'test-2008', 'data', '--page', '1', '--table', '1', '-o', str(work), '--store', store]) == 0
    assert yaml.safe_load((work / 'data.extraction.yaml').read_text())['created']['by'] == 'Ada Lovelace <ada@example.org>'
    (work / 'data.csv').write_text((work / 'data.csv').read_text() + '1,2\n2,3\n')
    assert main(['literature', 'add', str(work / 'data.extraction.yaml'), '--store', store]) == 0
    assert main(['literature', 'review', 'test-2008/data', '--approve', '--store', store]) == 0  # reviewer: the configured user
    entry = next(e for e in Store(store).entries() if e.meta['kind'] == 'extraction')
    assert entry.meta['extraction']['review']['reviewer'] == 'Ada Lovelace <ada@example.org>'
    assert entry.meta['imported_by'] == 'Ada Lovelace <ada@example.org>'

    assert main(['config', '--unset', 'user.email']) == 0
    assert config.identity() is None
    assert main(['literature', 'review', 'test-2008/data', '--approve', '--store', store]) == 1
    assert main(['config', '--unset', 'user.name']) == 0
    assert 'user' not in config.load()
    assert main(['config', '--set', 'store', str(tmp_path / 'other')]) == 0 and config.value('store') == str(tmp_path / 'other')


def test_store_command_with_store_setting(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    write_config(tmp_path, monkeypatch, {'store': str(tmp_path / 'store')})
    assert main(['store']) == 0  # 'store' is a global setting, not the options of the store command
    assert 'must be a mapping' not in capsys.readouterr().err
