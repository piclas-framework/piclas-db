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
import subprocess

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import pytest

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db import git
from piclas_db.piclas_db import main
from piclas_db.resolve import Origin, Requirement, resolve, synchronize
from piclas_db.store import Store
from tests.test_import import LXCAT, NIST_CSV
# ==================================================================================================================================
# The private repository is simulated by a local bare git repository (no network, no SSH)


@pytest.fixture(autouse=True)
def git_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    # commits in the store get the piclas-db user (set for all tests in conftest.py), not a git configuration
    for variable in ('GIT_AUTHOR_NAME', 'GIT_COMMITTER_NAME', 'GIT_AUTHOR_EMAIL', 'GIT_COMMITTER_EMAIL'):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', '/dev/null')  # no user.name of the machine running the tests
    monkeypatch.delenv('PICLAS_DB_MIRROR', raising=False)


@pytest.fixture
def remote(tmp_path: pathlib.Path) -> str:
    path = tmp_path / 'private.git'
    subprocess.run(['git', 'init', '--quiet', '--bare', str(path)], check=True)
    return str(path)


@pytest.fixture
def files(tmp_path: pathlib.Path) -> pathlib.Path:
    directory = tmp_path / 'Downloads'
    directory.mkdir()
    (directory / 'lxcat.txt').write_text(LXCAT)
    (directory / 'Ar_I_levels.csv').write_text(NIST_CSV)
    return directory


def log(remote: str) -> list[str]:
    return git.git(['log', '--format=%s'], cwd=pathlib.Path(remote)).splitlines()


def test_clone_import_push_and_second_machine(remote: str, files: pathlib.Path, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    first, second = tmp_path / 'first', tmp_path / 'second'
    assert main(['fetch', '--mirror', remote, '--store', str(first)]) == 0  # empty private repository
    assert main(['import', str(files / 'lxcat.txt'), '--store', str(first)]) == 0
    assert '1 local commit(s) not pushed' in capsys.readouterr().out
    assert main(['push', '--store', str(first)]) == 0
    assert log(remote) == ['Add lxcat cross-sections test-a+test-b/ar (retrieved 2026-06-01, sha256 ' + Store(first).entries()[0].meta['sha256'][:8] + ')']
    assert git.git(['log', '-1', '--format=%an <%ae>'], cwd=pathlib.Path(remote)) == 'piclas-db test <test@example.com>'  # the piclas-db user
    assert main(['push', '--store', str(first)]) == 0
    assert 'Nothing to push' in capsys.readouterr().out

    # Second machine: clone, import another file, push; the first machine gets it with fetch
    assert main(['fetch', '--mirror', remote, '--store', str(second)]) == 0
    assert len(Store(second).entries()) == 1
    assert main(['import', str(files / 'Ar_I_levels.csv'), '--retrieved', '2026-11-17', '--store', str(second)]) == 0
    assert main(['push', '--store', str(second)]) == 0
    assert main(['fetch', '--store', str(first)]) == 0  # remote of the clone is used
    assert len(Store(first).entries()) == 2
    assert (first / 'index.yaml').is_file()
    assert 'index.yaml' not in git.git(['ls-files'], cwd=first)  # generated locally, never committed


def test_existing_local_store_is_adopted(remote: str, files: pathlib.Path, tmp_path: pathlib.Path) -> None:
    local = tmp_path / 'store'
    assert main(['import', str(files / 'lxcat.txt'), '--store', str(local)]) == 0  # before a private repository exists
    message = synchronize(Store(local), remote)
    assert '1 local file(s) added' in message
    assert Store(local).is_repository
    assert len(Store(local).entries()) == 1
    assert list(tmp_path.glob('store.backup-*'))  # the old store is kept
    assert main(['push', '--store', str(local)]) == 0
    assert log(remote) == ['Add 1 file(s) from an existing local store']


def test_resolve(remote: str, files: pathlib.Path, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    first, second = tmp_path / 'first', tmp_path / 'second'
    synchronize(Store(first), remote)
    synchronize(Store(second), remote)
    main(['import', str(files / 'Ar_I_levels.csv'), '--retrieved', '2026-11-17', '--store', str(first)])
    main(['push', '--store', str(first)])
    main(['import', str(files / 'lxcat.txt'), '--store', str(second)])
    checksum = Store(second).entries()[0].meta['sha256']

    requirements = [Requirement.parse('lxcat/test-a+test-b/ar'), Requirement.parse('nist-asd/levels/ar'), Requirement.parse('lxcat/biagi-v7.1/xe')]
    origins = [resolution.origin for resolution in resolve(Store(second), requirements)]
    assert origins == [Origin.LOCAL, Origin.PRIVATE, Origin.MANUAL]

    assert Requirement.parse(f'lxcat/test-a+test-b/ar@{checksum[:8]}').matches(Store(second).entries()[0])
    assert not Requirement.parse('lxcat/test-a+test-b/ar@00000000').matches(Store(second).entries()[0])
    with pytest.raises(ValueError):
        Requirement.parse('lxcat')
    assert main(['fetch', '--store', str(second), '--need', 'lxcat/test-a+test-b/ar', 'nist-asd/levels/ar']) == 0
    assert main(['fetch', '--store', str(second), '--need', 'lxcat/biagi-v7.1/xe']) == 1
    assert 'manual download' in capsys.readouterr().out
    assert main(['fetch', '--store', str(second), '--need', 'nonsense']) == 1


def test_errors(remote: str, files: pathlib.Path, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    plain = tmp_path / 'plain'
    assert main(['fetch', '--store', str(plain)]) == 1  # no private repository configured
    assert 'no private repository' in capsys.readouterr().out
    assert main(['push', '--store', str(plain)]) == 1
    assert main(['fetch', '--mirror', str(tmp_path / 'missing.git'), '--store', str(plain)]) == 1
    clone = tmp_path / 'clone'
    synchronize(Store(clone), remote)
    with pytest.raises(git.GitError, match='is a clone of'):
        synchronize(Store(clone), str(tmp_path / 'other.git'))
    main(['import', str(files / 'lxcat.txt'), '--store', str(clone)])
    entry = Store(clone).entries()[0]
    entry.path.write_text('changed')
    assert main(['push', '--store', str(clone)]) == 1  # changed files are never pushed
    assert 'Not pushed' in capsys.readouterr().out
