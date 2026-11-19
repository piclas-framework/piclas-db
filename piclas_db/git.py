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
"""Thin wrapper around the git command line for the private source repository

Authentication is left entirely to git and SSH (the user's own keys and permissions); piclas-db never handles credentials. Git is
run non-interactively, so a missing permission fails immediately instead of waiting for a password prompt.
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import os
import pathlib
import shutil
import subprocess
from typing import Optional
# ==================================================================================================================================


class GitError(Exception):
    """A git command failed"""


def environment() -> dict[str, str]:
    env = dict(os.environ)
    env['GIT_TERMINAL_PROMPT'] = '0'  # never ask for a user name or password
    env.setdefault('GIT_SSH_COMMAND', 'ssh -o BatchMode=yes')  # never ask for a passphrase or host confirmation
    from piclas_db import config  # noqa: PLC0415

    user = config.identity()
    if user is not None:  # commits in the store carry the person who added the data (piclas-db config user.*)
        for role in ('AUTHOR', 'COMMITTER'):
            env.setdefault(f'GIT_{role}_NAME', user[0])
            env.setdefault(f'GIT_{role}_EMAIL', user[1])
    return env


def git(arguments: list[str], cwd: Optional[pathlib.Path] = None) -> str:
    if shutil.which('git') is None:
        raise GitError('git is not installed')
    process = subprocess.run(['git', *arguments], cwd=cwd, capture_output=True, text=True, env=environment(), check=False)
    if process.returncode != 0:
        message = (process.stderr or process.stdout).strip().splitlines()
        hint = ''
        if any(word in ' '.join(message) for word in ('Permission denied', 'Could not read from remote', 'Authentication failed')):
            hint = ' (no access: check your SSH key and your permissions for the private repository)'
        raise GitError(f'git {arguments[0]} failed: {message[-1] if message else "unknown error"}{hint}')
    return process.stdout.strip()


def is_repository(path: pathlib.Path) -> bool:
    return (path / '.git').exists()


def clone(url: str, path: pathlib.Path) -> None:
    git(['clone', '--quiet', url, str(path)])


def has_commits(path: pathlib.Path) -> bool:
    try:
        git(['rev-parse', '--verify', '--quiet', 'HEAD'], cwd=path)
    except GitError:
        return False
    return True


def has_upstream(path: pathlib.Path) -> bool:
    try:
        git(['rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}'], cwd=path)
    except GitError:
        return False
    return True


def remote_url(path: pathlib.Path) -> Optional[str]:
    try:
        return git(['remote', 'get-url', 'origin'], cwd=path) or None
    except GitError:
        return None


def pull(path: pathlib.Path) -> None:
    """Update from the remote; rebases local commits (imports only add new files, so there are no conflicts)"""
    if has_upstream(path):
        git(['pull', '--quiet', '--rebase'], cwd=path)
        return
    if not remote_url(path):
        return
    # Clone of a repository that was empty at the time: track the remote branch as soon as it exists
    git(['fetch', '--quiet', 'origin'], cwd=path)
    branches = [line.strip() for line in git(['branch', '--remotes'], cwd=path).splitlines() if '->' not in line]
    if not branches:
        return
    branch = 'origin/main' if 'origin/main' in branches else branches[0]
    if has_commits(path):
        git(['branch', '--quiet', f'--set-upstream-to={branch}'], cwd=path)
        git(['pull', '--quiet', '--rebase'], cwd=path)
    else:
        git(['checkout', '--quiet', '-B', branch.split('/', 1)[1], '--track', branch], cwd=path)


def changes(path: pathlib.Path) -> list[str]:
    """Uncommitted changes in a clone ('git status --porcelain' lines; untracked files included)"""
    return [line for line in git(['status', '--porcelain'], cwd=path).splitlines() if line.strip()]


def exclude(path: pathlib.Path, pattern: str) -> None:
    """Ignore a file in this clone only (.git/info/exclude), without committing a .gitignore"""
    exclude_file = path / '.git' / 'info' / 'exclude'
    exclude_file.parent.mkdir(parents=True, exist_ok=True)
    lines = exclude_file.read_text().splitlines() if exclude_file.exists() else []
    if pattern not in lines:
        exclude_file.write_text('\n'.join([*lines, pattern]) + '\n')


def commit(path: pathlib.Path, files: list[pathlib.Path], message: str) -> bool:
    """Commit the given files (or all changes if no files are given); returns False if there was nothing to commit"""
    git(['add', '--', *[str(file.relative_to(path)) for file in files]] if files else ['add', '--all'], cwd=path)
    if not git(['status', '--porcelain'], cwd=path):
        return False
    git(['commit', '--quiet', '-m', message], cwd=path)
    return True


def unpushed(path: pathlib.Path) -> int:
    """Number of local commits that are not on the remote"""
    if not has_commits(path):
        return 0
    if not has_upstream(path):
        return int(git(['rev-list', '--count', 'HEAD'], cwd=path))
    return int(git(['rev-list', '--count', '@{u}..HEAD'], cwd=path))


def push(path: pathlib.Path) -> None:
    if has_upstream(path):
        git(['pull', '--quiet', '--rebase'], cwd=path)
        git(['push', '--quiet'], cwd=path)
    else:
        git(['push', '--quiet', '--set-upstream', 'origin', 'HEAD'], cwd=path)
