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
"""Parser for LXCat text downloads (cross-section data format, see the header of every LXCat download)

A download can contain several databases. Each database section starts with a line of 'x' characters followed by 'DATABASE:'
and 'PERMLINK:' lines. Each collision process is a block with an optional type keyword (ELASTIC, EFFECTIVE, EXCITATION,
IONIZATION, ATTACHMENT; missing for ion-neutral data), header lines (SPECIES:, PROCESS:, PARAM.:, COMMENT:, UPDATED:, COLUMNS:)
and a table between two lines of at least five dashes.
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import datetime
import re
from dataclasses import dataclass, field
from typing import Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import numpy as np
# ==================================================================================================================================

TYPE_KEYWORDS = ('ELASTIC', 'EFFECTIVE', 'EXCITATION', 'IONIZATION', 'ATTACHMENT')
HEADER_KEYS = ('SPECIES', 'PROCESS', 'PARAM.', 'COMMENT', 'UPDATED', 'COLUMNS')
DASHES = re.compile(r'^-{5,}\s*$')


@dataclass
class LXCatProcess:
    database: str
    type: str  # keyword, or the process type given at the end of PROCESS (e.g. 'Backscat', 'Isotropic') for ion-neutral data
    species: str  # e.g. 'e / Ar', 'Ar^+ / Ar'
    process: str
    parameters: str = ''
    comments: list[str] = field(default_factory=list)
    updated: Optional[str] = None
    data: np.ndarray = field(default_factory=lambda: np.empty((0, 2)))

    @property
    def target(self) -> str:
        """Target species, e.g. 'Ar' for 'e / Ar'"""
        return self.species.split('/')[-1].strip()

    @property
    def projectile(self) -> str:
        return self.species.split('/')[0].strip()


@dataclass
class LXCatDatabase:
    name: str
    permlink: Optional[str] = None


@dataclass
class LXCatFile:
    generated: Optional[datetime.date] = None
    references: list[str] = field(default_factory=list)  # recommended reference lines
    databases: list[LXCatDatabase] = field(default_factory=list)
    processes: list[LXCatProcess] = field(default_factory=list)


def is_lxcat(text: str) -> bool:
    """LXCat download: a DATABASE: line and either collision blocks (SPECIES:/PROCESS:) or swarm data, at the start of lines"""
    has_database = re.search(r'^DATABASE:', text, re.MULTILINE) is not None
    has_data = re.search(r'^(SPECIES|PROCESS):', text, re.MULTILINE) is not None or 'E/N' in text
    return has_database and has_data


def parse_generated(text: str) -> Optional[datetime.date]:
    match = re.search(r'Generated on (\d{1,2} \w{3} \d{4})', text[:2000])
    if not match:
        return None
    try:
        return datetime.datetime.strptime(match.group(1), '%d %b %Y').date()
    except ValueError:
        return None


@dataclass
class Block:
    """Header of a collision process while it is parsed"""

    fields: dict[str, str] = field(default_factory=dict)
    comments: list[str] = field(default_factory=list)

    def finish(self, database: str, keyword: Optional[str], table: list[list[float]]) -> LXCatProcess:
        process = self.fields.get('process', '')
        process_type = keyword or (process.rsplit(',', 1)[-1].strip() if ',' in process else 'UNKNOWN')
        return LXCatProcess(
            database=database,
            type=process_type,
            species=self.fields.get('species', ''),
            process=process,
            parameters=self.fields.get('param', ''),
            comments=self.comments,
            updated=self.fields.get('updated'),
            data=np.array(table, dtype=np.float64).reshape(-1, 2),
        )


def parse_lxcat(text: str) -> LXCatFile:
    """Parse an LXCat download; raises ValueError if a table cannot be read"""
    result = LXCatFile(generated=parse_generated(text))
    lines = text.splitlines()

    in_references = False
    database = ''
    block: Optional[Block] = None
    keyword: Optional[str] = None
    table: Optional[list[list[float]]] = None
    for number, raw in enumerate(lines, start=1):
        line = raw.strip()
        if line.startswith('RECOMMENDED REFERENCE FORMAT'):
            in_references = True
            continue
        if in_references:
            if line.startswith('- '):
                result.references.append(line[2:].strip())
                continue
            in_references = False

        if table is not None:
            if DASHES.match(line):
                assert block is not None
                result.processes.append(block.finish(database, keyword, table))
                block, keyword, table = None, None, None
                continue
            try:
                values = [float(value) for value in line.split()]
            except ValueError as e:
                raise ValueError(f'line {number}: no numbers in table: {line!r}') from e
            if len(values) != 2:
                raise ValueError(f'line {number}: expected two columns, found {len(values)}')
            table.append(values)
            continue

        if line.startswith('DATABASE:'):
            database = line.split(':', 1)[1].strip()
            result.databases.append(LXCatDatabase(name=database))
        elif line.startswith('PERMLINK:') and result.databases:
            result.databases[-1].permlink = line.split(':', 1)[1].strip()
        elif line in TYPE_KEYWORDS:
            keyword, block = line, Block()
        elif ':' in line and line.split(':', 1)[0] in HEADER_KEYS:
            key, value = (part.strip() for part in line.split(':', 1))
            if block is None or (key == 'SPECIES' and 'species' in block.fields):
                block = Block()  # ion-neutral data have no type keyword, a block starts with SPECIES:
            if key == 'COMMENT':
                block.comments.append(value)
            else:
                block.fields[key.lower().rstrip('.')] = value
        elif DASHES.match(line) and block is not None and 'species' in block.fields:
            table = []
    return result


def validate(file: LXCatFile) -> list[str]:
    """Problems found in the parsed data (empty list if the file is fine)"""
    problems = []
    if not file.processes:
        problems.append('no collision processes found')
    for process in file.processes:
        name = f'{process.database}: {process.process or process.species}'
        if len(process.data) < 2:
            problems.append(f'{name}: fewer than two data points')
            continue
        if np.any(np.diff(process.data[:, 0]) < 0.0):
            problems.append(f'{name}: energies not increasing')
        if np.any(process.data < 0.0) or not np.all(np.isfinite(process.data)):
            problems.append(f'{name}: negative or non-finite values')
    return problems
