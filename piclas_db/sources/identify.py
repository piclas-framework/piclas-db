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
"""Identification of original data files by their content"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import datetime
import pathlib
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.sources.own import OwnDataError, is_own_data, parse_own_data
from piclas_db.sources.atct import ATcTError, is_atct, parse_atct
from piclas_db.sources.lxcat import LXCatFile, compare, is_lxcat, is_lxcat_xml, parse_lxcat, parse_lxcat_xml, validate, zip_texts
from piclas_db.sources.nist import is_nist_levels, parse_nist_levels
# ==================================================================================================================================


class IdentifyError(Exception):
    """File cannot be identified or is invalid"""


@dataclass
class Identified:
    provider: str  # 'lxcat', 'nist-asd' or 'custom'
    kind: str  # 'cross-sections', 'swarm', 'levels' or 'custom'
    dataset: str  # sub-directory in the store, e.g. 'biagi-v7.1+phelps/ar'
    species: list[str] = field(default_factory=list)
    retrieved: Optional[datetime.date] = None
    details: dict[str, object] = field(default_factory=dict)


def slug(text: str) -> str:
    return re.sub(r'[^a-z0-9.+_-]+', '-', text.lower()).strip('-') or 'unnamed'


def database_slug(name: str) -> str:
    """Short database name: 'Biagi-v7.1 (Magboltz version 7.1)' -> 'biagi-v7.1', 'Phelps database' -> 'phelps'"""
    return slug(re.sub(r'\(.*?\)|\bdatabase\b', '', name, flags=re.IGNORECASE).strip().split(' ')[0])


def read_text(path: pathlib.Path) -> Optional[str]:
    raw = path.read_bytes()
    if b'\x00' in raw[:4096]:
        return None  # binary file
    return raw.decode('utf-8', errors='replace')


def atct_dataset(atct_id: str) -> str:
    """Store name of an ATcT ID: '630-08-0*0' -> '630-08-0-0' ('*' is not a good character in paths)"""
    return atct_id.strip().replace('*', '-')


def atct_id_of(dataset: str) -> str:
    """Inverse of atct_dataset: the last '-' separates the state number"""
    head, _, state = dataset.rpartition('-')
    return f'{head}*{state}'


def lxcat_identified(parsed: LXCatFile, details: dict[str, object]) -> Identified:
    """Store location and meta data of an LXCat cross-section download (TXT, XML or both in a ZIP)"""
    problems = validate(parsed)
    if problems:
        raise IdentifyError('invalid LXCat data: ' + '; '.join(problems))
    databases = sorted({database_slug(process.database) for process in parsed.processes})
    targets = sorted({process.target for process in parsed.processes})
    return Identified(
        provider='lxcat',
        kind='cross-sections',
        dataset='+'.join(databases) + '/' + '+'.join(slug(target) for target in targets),
        species=targets,
        retrieved=parsed.generated,
        details={
            **details,
            'databases': [{'name': d.name, 'permlink': d.permlink} for d in parsed.databases],
            'references': parsed.references,
            'processes': dict(Counter(f'{process.species}: {process.type}' for process in parsed.processes)),
        },
    )


def identify_lxcat_zip(path: pathlib.Path) -> Identified:
    """ZIP downloaded from LXCat with TXT and/or XML: both are read and must contain exactly the same data"""
    try:
        texts = zip_texts(path)
        parsed = {kind: (parse_lxcat(text) if kind == 'txt' else parse_lxcat_xml(text)) for kind, text in texts.items()}
    except (ValueError, zipfile.BadZipFile) as e:
        raise IdentifyError(f'LXCat ZIP cannot be read: {e}') from e
    if not parsed:
        raise IdentifyError('ZIP without LXCat TXT or XML file (use --custom NAME to store other data)')
    details: dict[str, object] = {'format': 'zip', 'contents': sorted(parsed)}
    if len(parsed) == 2:
        differences = compare(parsed['txt'], parsed['xml'])
        if differences:
            raise IdentifyError('TXT and XML in the ZIP differ: ' + '; '.join(differences[:5]) + (f' (and {len(differences) - 5} more)' if len(differences) > 5 else ''))
        details['txt_xml'] = f'identical ({len(parsed["txt"].processes)} processes)'
    return lxcat_identified(parsed.get('txt') or parsed['xml'], details)


def identify(
    path: pathlib.Path,
    species: Optional[str] = None,
    custom: Optional[str] = None,
    literature: Optional[str] = None,
    doi: Optional[str] = None,
    reference: Optional[str] = None,
) -> Identified:
    """Determine provider, kind and dataset of a downloaded file; raises IdentifyError for unknown or invalid files"""
    if literature:
        if not path.read_bytes()[:5] == b'%PDF-':
            raise IdentifyError('--literature expects the paper as PDF')
        if not (doi or reference):
            raise IdentifyError('--literature needs --doi or --reference (how to cite the paper)')
        return Identified(provider='literature', kind='paper', dataset=slug(literature), details={'doi': doi, 'reference': reference})
    if custom:
        return Identified(provider='custom', kind='custom', dataset=slug(custom), species=[species] if species else [])

    if zipfile.is_zipfile(path):
        return identify_lxcat_zip(path)

    text = read_text(path)
    if text is None:
        raise IdentifyError('binary file, not an LXCat or NIST ASD download (use --custom NAME to store other data)')

    if is_own_data(text):
        try:
            content = parse_own_data(text)
        except OwnDataError as e:
            raise IdentifyError(f'own data: {e}') from e
        return Identified(
            provider='own',
            kind='species-parameters',
            retrieved=datetime.date.today(),  # own data: the date of the import
            dataset=slug(str(content['name'])),
            species=sorted(content['species']),
            details={'description': content.get('description'), 'species_count': len(content['species'])},
        )

    if is_atct(text):
        try:
            records = parse_atct(text)
        except ATcTError as e:
            raise IdentifyError(f'ATcT response cannot be read: {e}') from e
        if len(records) != 1:
            raise IdentifyError(f'ATcT response with {len(records)} species: store one species per file (piclas-db atct get <ATcT ID>)')
        record = records[0]
        return Identified(
            provider='atct',
            kind='species',
            dataset=atct_dataset(record.atct_id),
            species=[record.formula],
            details={'atct_id': record.atct_id, 'version': record.version, 'name': record.name, 'formula': record.formula},
        )

    if is_lxcat_xml(text):
        try:
            parsed = parse_lxcat_xml(text)
        except ValueError as e:
            raise IdentifyError(f'LXCat XML cannot be read: {e}') from e
        return lxcat_identified(parsed, {'format': 'xml'})

    if is_lxcat(text):
        try:
            parsed = parse_lxcat(text)
        except ValueError as e:
            raise IdentifyError(f'LXCat file cannot be read: {e}') from e
        if not parsed.processes and 'E/N' in text:
            databases = [database_slug(database.name) for database in parsed.databases] or ['unknown']
            return Identified(
                provider='lxcat',
                kind='swarm',
                dataset='+'.join(databases) + '/swarm',
                retrieved=parsed.generated,
                details={'databases': [{'name': d.name, 'permlink': d.permlink} for d in parsed.databases], 'references': parsed.references},
            )
        return lxcat_identified(parsed, {'format': 'txt'})

    if is_nist_levels(text):
        try:
            parsed_levels = parse_nist_levels(text, name_hint=path.name)
        except ValueError as e:
            raise IdentifyError(f'NIST ASD file cannot be read: {e}') from e
        name = species or parsed_levels.species
        if not name:
            raise IdentifyError('NIST ASD levels: species not found in the file or its name (use --species, e.g. --species ArIon1)')
        if len(parsed_levels.levels) == 0:
            raise IdentifyError('NIST ASD levels: no levels with J and energy found')
        return Identified(
            provider='nist-asd',
            kind='levels',
            dataset=f'levels/{slug(name)}',
            species=[name],
            details={'unit': parsed_levels.unit, 'levels': len(parsed_levels.levels), 'rows skipped': parsed_levels.skipped},
        )

    raise IdentifyError('not recognized as LXCat or NIST ASD download (use --custom NAME to store other data)')
