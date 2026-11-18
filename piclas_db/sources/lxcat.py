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
from typing import Any, Optional

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


# ----------------------------------------------------------------------------------------------------------------------------------
# Canonical form: the same process downloaded as TXT or as XML gives the same values
# ----------------------------------------------------------------------------------------------------------------------------------
XML_TYPES = {'elastic': 'ELASTIC', 'effective': 'EFFECTIVE', 'excitation': 'EXCITATION', 'ionization': 'IONIZATION', 'attachment': 'ATTACHMENT'}
PARAMETER_NAMES = {'mm': 'm/M', 'm/m': 'm/M', 'e': 'E', 'mi': 'Mi', 'mim': 'Mi/M', 'mi/m': 'Mi/M', 'g': 'g'}


def canonical_process(process: str) -> str:
    """'Ar^+ + Ar -> , Backscat' and 'Ar+ + Ar ->, Backscat' -> 'Ar+ + Ar ->, Backscat' (no '^', single spaces, no space before ',')"""
    return re.sub(r'\s+,', ',', ' '.join(process.replace('^', '').split()))


def canonical_parameters(parameters: str) -> str:
    """'m/M = 0.0000136, complete set' -> 'm/M = 1.36e-05, complete set'; numbers with %g, units of thresholds kept as eV"""
    parts = []
    for item in (part.strip() for part in parameters.split(',')):
        match = re.fullmatch(r'([A-Za-z/]+)\s*=\s*([-+0-9.eE]+)\s*(eV)?', item)
        if match:
            name = PARAMETER_NAMES.get(match.group(1).lower(), match.group(1))
            parts.append(f'{name} = {float(match.group(2)):g}' + (' eV' if name == 'E' else ''))
        elif item:
            parts.append(item)
    return ', '.join(parts)


def fingerprint(process: LXCatProcess) -> tuple[str, str, str, str]:
    """Identity of a process in LXCat: database, species, process and update time (unique per LXCat process)"""
    return process.database.split(' ')[0].lower(), process.species.replace(' ', ''), canonical_process(process.process), (process.updated or '').strip()


# ----------------------------------------------------------------------------------------------------------------------------------
# XML downloads
# ----------------------------------------------------------------------------------------------------------------------------------
def is_lxcat_xml(text: str) -> bool:
    return re.search(r'<lxcat[\s>]', text[:2000]) is not None


def parse_lxcat_xml(text: str) -> LXCatFile:
    """LXCat XML download in the same model as the TXT (type keywords, species 'e / Ar', PROCESS with type, PARAM. text)"""
    import xml.etree.ElementTree as ElementTree  # noqa: PLC0415  (standard library, parses only, no network or entities)

    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as e:
        raise ValueError(f'XML cannot be read: {e}') from e
    result = LXCatFile()
    created = root.get('created', '')
    match = re.match(r'(\d{4}-\d{2}-\d{2})', created)
    if match:
        result.generated = datetime.date.fromisoformat(match.group(1))
    result.references = [(element.text or '').strip().removeprefix('- ').strip() for element in root.iter('Reference') if (element.text or '').strip().startswith('-')]
    for database in root.iter('Database'):
        name = database.get('name') or database.get('id') or ''
        result.databases.append(LXCatDatabase(name=name, permlink=(database.findtext('Permlink') or '').strip() or None))
        for process in database.iter('Process'):
            kind = process.get('type', '')
            reactants = [(element.text or '').strip() for element in process.iter('Reactant')]
            species = ' / '.join(reactants[:2]) if len(reactants) >= 2 else ' / '.join(reactants)
            reaction = ' '.join((process.findtext('Reaction') or '').split())
            parameters = []
            parameter_elements = process.find('Parameters')
            for element in list(parameter_elements) if parameter_elements is not None else []:
                value = (element.text or '').strip()
                if element.tag == 'Parameter':
                    parameters.append(value)
                else:
                    label = PARAMETER_NAMES.get(element.tag.lower(), element.tag)
                    parameters.append(f'{label} = {float(value):g}' + (' eV' if label == 'E' else ''))
            numbers_x = [float(value) for value in (process.findtext('DataX') or '').split()]
            numbers_y = [float(value) for value in (process.findtext('DataY') or '').split()]
            if len(numbers_x) != len(numbers_y):
                raise ValueError(f'{name}: {reaction}: {len(numbers_x)} energies but {len(numbers_y)} cross-sections')
            data_y = process.find('DataY')
            units = (data_y.get('units') if data_y is not None else None) or 'm2'
            if units.replace('^', '') != 'm2':
                raise ValueError(f'{name}: {reaction}: cross-section unit {units} (expected m2)')
            result.processes.append(
                LXCatProcess(
                    database=name,
                    type=XML_TYPES.get(kind.lower(), kind),
                    species=species,
                    process=f'{reaction}, {kind}',
                    parameters=', '.join(parameters),
                    comments=[' '.join((element.text or '').split()) for element in process.iter('Comment') if (element.text or '').strip()],
                    updated=(process.findtext('Updated') or '').strip() or None,
                    data=np.column_stack([numbers_x, numbers_y]) if numbers_x else np.empty((0, 2)),
                )
            )
    return result


def compare(first: LXCatFile, second: LXCatFile) -> list[str]:
    """Differences between two downloads of the same selection (e.g. TXT and XML of one ZIP); empty list: the same data"""
    by_first = {fingerprint(process): process for process in first.processes}
    by_second = {fingerprint(process): process for process in second.processes}
    differences = [f'only in {"the first" if key in by_first else "the second"} file: {key[0]} {key[1]} {key[2]} ({key[3]})' for key in sorted(set(by_first) ^ set(by_second))]
    for key in sorted(set(by_first) & set(by_second)):
        a, b = by_first[key], by_second[key]
        label = f'{key[0]} {key[1]} {key[2]}'
        if a.type.upper() != b.type.upper():
            differences.append(f'{label}: type {a.type} / {b.type}')
        if canonical_parameters(a.parameters) != canonical_parameters(b.parameters):
            differences.append(f'{label}: parameters {a.parameters!r} / {b.parameters!r}')
        if ' '.join(' '.join(a.comments).split()) != ' '.join(' '.join(b.comments).split()):
            differences.append(f'{label}: comments differ')
        if a.data.shape != b.data.shape or not np.array_equal(a.data, b.data):
            differences.append(f'{label}: data differ ({len(a.data)} / {len(b.data)} points)')
    return differences


def load_lxcat(path: Any) -> LXCatFile:
    """LXCat download from a TXT, XML or ZIP file (a ZIP is read from its TXT, which is checked against its XML on import)"""
    import pathlib  # noqa: PLC0415
    import zipfile  # noqa: PLC0415

    path = pathlib.Path(path)
    if zipfile.is_zipfile(path):
        texts = zip_texts(path)
        if 'txt' in texts:
            return parse_lxcat(texts['txt'])
        if 'xml' in texts:
            return parse_lxcat_xml(texts['xml'])
        raise ValueError(f'{path.name}: no LXCat TXT or XML file in the ZIP')
    text = path.read_text(encoding='utf-8', errors='replace')
    return parse_lxcat_xml(text) if is_lxcat_xml(text) else parse_lxcat(text)


def zip_texts(path: Any) -> dict[str, str]:
    """LXCat TXT and XML files in a ZIP downloaded from LXCat ({'txt': ..., 'xml': ...}); images and other files are ignored"""
    import zipfile  # noqa: PLC0415

    texts: dict[str, str] = {}
    with zipfile.ZipFile(path) as archive:
        for member in archive.infolist():
            suffix = member.filename.rsplit('.', 1)[-1].lower()
            if suffix in ('txt', 'xml') and member.file_size < 50_000_000:
                content = archive.read(member).decode('utf-8', errors='replace')
                if (suffix == 'xml' and is_lxcat_xml(content)) or (suffix == 'txt' and is_lxcat(content)):
                    if suffix in texts:
                        raise ValueError(f'more than one LXCat {suffix.upper()} file in the ZIP')
                    texts[suffix] = content
    return texts
