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
"""Assembly of a database from original files in the store according to a recipe ('piclas-db build')

LXCat processes are mapped to PICLas groups as follows (fixing the classification errors of the former create_xsec_db_lxcat.py):

* ELASTIC, EFFECTIVE -> ELASTIC, EFFECTIVE dataset of the pair
* EXCITATION -> ROTATION, VIBRATION or ELECTRONIC/<threshold>: rotational if the process names a rotational state (rot, J=),
  vibrational if it names a vibrational state (v=, vib), otherwise electronic
* IONIZATION -> REACTION/<products>, products in PICLas names, heavy species first, electrons last (e.g. ArIon1-electron-electron)
* ion-neutral processes (no type keyword) by their name in PROCESS: Backscat -> BACKSCATTER, Isotropic -> ELASTIC
* ATTACHMENT is not supported by PICLas cross-section chemistry and is skipped with a note

The collision pair is named <target>-<projectile> in PICLas names (e.g. Ar-electron, Ar-ArIon1); PICLas finds both orders.
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import itertools
import re
from dataclasses import dataclass, field
from typing import Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import numpy as np

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.model import CollisionPair, CrossSection, Database, Provenance, Reaction, Species, XSecKind
from piclas_db.recipe import ALL_DOWNLOADS, CrossSectionSelection, LevelSelection, LiteratureSelection, Recipe
from piclas_db.reference import CM_TO_K, EV_TO_K
from piclas_db.resolve import Origin, Requirement, Resolution
from piclas_db.schema import Schema
from piclas_db.sources.identify import database_slug
from piclas_db.sources.lxcat import LXCatFile, LXCatProcess, canonical_parameters, canonical_process, fingerprint, load_lxcat
from piclas_db.sources.nist import parse_nist_levels
from piclas_db.sources.own import LEVEL_KEYS, level_array
from piclas_db.store import Store, StoreEntry
# ==================================================================================================================================

RYDBERG_EV = 13.605693122990  # Rydberg energy in eV (CODATA 2022)
ION_NEUTRAL_TYPES = {'backscat': XSecKind.BACKSCATTER, 'isotropic': XSecKind.ELASTIC}


class BuildError(Exception):
    """Database cannot be built"""


@dataclass
class BuildReport:
    added: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    files: list[StoreEntry] = field(default_factory=list)  # LXCat downloads used (also those found per process with 'source: lxcat')
    combined: dict[str, list[tuple[str, np.ndarray]]] = field(default_factory=dict)  # dataset -> (part, all data of its source)


# ----------------------------------------------------------------------------------------------------------------------------------
# Names
# ----------------------------------------------------------------------------------------------------------------------------------
def piclas_name(name: str) -> str:
    """LXCat species name in PICLas notation: 'E' -> 'electron', 'Ar+' / 'Ar^+' -> 'ArIon1', 'Ar++' -> 'ArIon2', 'Ar*' -> 'Ar'"""
    name = name.strip().rstrip('*').strip()
    name = re.sub(r'\(.*\)$', '', name).strip()  # excited state in parentheses, e.g. Ar*(11.55eV) or Ar(1S5)
    name = name.rstrip('*')
    if name.lower() in ('e', 'e-', 'electron'):
        return 'electron'
    match = re.fullmatch(r'(.+?)\^(\d+)\+', name) or re.fullmatch(r'(.+?)\^?\+(\d+)', name)
    if match:
        return f'{match.group(1)}Ion{match.group(2)}'
    match = re.fullmatch(r'(.+?)\^?(\++)', name)
    if match:
        return f'{match.group(1)}Ion{len(match.group(2))}'
    return name


def products(process: str) -> list[str]:
    """Products of an LXCat process in PICLas names, heavy species first, electrons last"""
    right = process.split('->', 1)[1].split(',', 1)[0] if '->' in process else ''
    names = [piclas_name(part) for part in right.split(' + ') if part.strip()]
    heavy = [name for name in names if name != 'electron']
    return heavy + ['electron'] * (len(names) - len(heavy))


def threshold(process: LXCatProcess) -> Optional[float]:
    match = re.search(r'E\s*=\s*([0-9.eE+-]+)\s*eV', process.parameters)
    return float(match.group(1)) if match else None


def excitation_kind(process: LXCatProcess) -> XSecKind:
    text = process.process.split(',', 1)[0]
    if re.search(r'\brot|\bJ\s*=|\(J', text, re.IGNORECASE):
        return XSecKind.ROTATION
    if re.search(r'v\s*=\s*\d|\bvib', text, re.IGNORECASE):
        return XSecKind.VIBRATION
    return XSecKind.ELECTRONIC


def info(process: LXCatProcess) -> str:
    """LXCat header of the process, in the form of the former create_xsec_db_lxcat.py, with process and parameters in canonical
    form, so that a TXT and an XML download of the same data give the same text"""
    fields = {'SPECIES': process.species, 'PROCESS': canonical_process(process.process), 'PARAM.': canonical_parameters(process.parameters)}
    if process.comments:
        fields['COMMENT'] = ' '.join(process.comments)
    if process.updated:
        fields['UPDATED'] = process.updated
    return str(fields)


def reference(file: LXCatFile, database: str) -> Optional[str]:
    """Recommended reference line of the database, e.g. 'Biagi-v7.1 database, www.lxcat.net, retrieved on June 1, 2026.'"""
    short = database.split(' ', maxsplit=1)[0].lower()
    return next((line for line in file.references if line.lower().startswith(short)), None)


def source_provenance(entry: StoreEntry) -> dict[str, object]:
    return {'* Source': f'{entry.meta.get("file")} (sha256 {entry.meta.get("sha256")})'}


# ----------------------------------------------------------------------------------------------------------------------------------
# Cross-sections
# ----------------------------------------------------------------------------------------------------------------------------------
Found = tuple[LXCatProcess, LXCatFile, StoreEntry]  # a process with its download and its file in the store


def select_processes(found: list[Found], selection: CrossSectionSelection) -> list[Found]:
    """Processes of one species and database; expected processes ('processes:') must all be there"""
    candidates = [item for item in found if item[0].species.replace(' ', '') == selection.species.replace(' ', '')]
    databases = sorted({item[0].database for item in candidates})
    if selection.database:
        databases = [name for name in databases if name.lower().startswith(selection.database.lower())]
    if not databases:
        raise BuildError(f'{selection.source}: no data for {selection.species!r}' + (f' in database {selection.database!r}' if selection.database else ''))
    if len(databases) > 1:
        raise BuildError(f'{selection.source}: {selection.species!r} is in several databases ({", ".join(databases)}); select one with "database"')
    chosen = [item for item in candidates if item[0].database == databases[0]]
    if selection.processes:
        missing = [part for part in selection.processes if not any(part in item[0].process for item in chosen)]
        if missing:
            raise BuildError(
                f'{selection.source}: no process {", ".join(repr(part) for part in missing)} for {selection.species!r} in {databases[0]}: download it from LXCat '
                f'(piclas-db guide lxcat/{database_slug(databases[0])}/<species>) and import it'
            )
        chosen = [item for item in chosen if any(part in item[0].process for part in selection.processes)]
    return chosen


def lxcat_index(store: Store) -> list[Found]:
    """Every process of every LXCat cross-section download in the store"""
    found = []
    for entry in store.entries():
        if entry.meta.get('provider') == 'lxcat' and entry.meta.get('kind') == 'cross-sections':
            file = load_lxcat(entry.path)
            found.extend((process, file, entry) for process in file.processes)
    return found


def merge_downloads(found: list[Found], report: BuildReport, label: str) -> list[Found]:
    """Processes of several downloads of the same database and species: union; the same process (fingerprint) once, from the newest
    download; a newer update of a process replaces the older; the same fingerprint with different data is a conflict"""
    by_process: dict[tuple[str, str, str], list[Found]] = {}
    for item in found:
        database, species, process, _ = fingerprint(item[0])
        by_process.setdefault((database, species, process), []).append(item)
    merged = []
    for key, items in by_process.items():
        newest_update = max(str(item[0].updated or '') for item in items)
        current = [item for item in items if str(item[0].updated or '') == newest_update]
        if len({str(item[0].updated or '') for item in items}) > 1:
            older = sorted({str(item[0].updated or '') for item in items} - {newest_update})
            report.notes.append(f'{label}: {key[2]}: updated {", ".join(older)} -> {newest_update}, the newest is used')
        reference = current[0][0].data
        conflicting = [item for item in current if item[0].data.shape != reference.shape or not np.array_equal(item[0].data, reference)]
        if conflicting:
            files = ', '.join(sorted({item[2].relative for item in current}))
            raise BuildError(f'{label}: {key[2]} ({newest_update}) differs between downloads with the same update time ({files}); pin one with @sha256')
        newest = max(current, key=lambda item: (str(item[2].meta.get('retrieved', '')), item[2].relative))
        if len(current) > 1:
            report.notes.append(f'{label}: {key[2]} in {len(current)} downloads (identical), taken from {newest[2].relative}')
        merged.append(newest)
    position = {id(item): index for index, item in enumerate(found)}
    return sorted(merged, key=lambda item: position[id(item)])  # order of the downloads


def add_cross_sections(database: Database, selection: CrossSectionSelection, found: list[Found], report: BuildReport) -> list[StoreEntry]:
    """Cross-sections of one selection; returns the files used"""
    chosen = select_processes(found, selection)
    if selection.source.dataset == ALL_DOWNLOADS:
        chosen = merge_downloads(chosen, report, f'{selection.database} {selection.species}')
    first = chosen[0][0]
    pair_name = selection.pair or f'{piclas_name(first.target)}-{piclas_name(first.projectile)}'
    pair = database.collision_pairs.setdefault(pair_name, CollisionPair(name=pair_name))

    used: list[StoreEntry] = []
    for process, file, entry in chosen:
        kind, group, key = classify(process, selection, report)
        if kind is None:
            continue
        value = threshold(process)
        if group in ('ROTATION', 'VIBRATION', 'ELECTRONIC'):
            if value is None:
                report.notes.append(f'{pair_name}: {process.process}: no threshold in PARAM., skipped')
                continue
            key = str(value)
        if any(existing.group == group and existing.key == key for existing in pair.cross_sections):
            report.notes.append(f'{pair_name}: {group + "/" if group else ""}{key} exists already, {process.process} skipped')
            continue
        provenance = Provenance(reference=reference(file, process.database), info=info(process), extra=source_provenance(entry))
        pair.cross_sections.append(CrossSection(kind=kind, key=key, data=process.data.copy(), group=group, threshold=value, provenance=provenance))
        report.added.append(f'/Cross-Sections/{pair_name}/' + (f'{group}/' if group else '') + key + ('' if selection.source.dataset != ALL_DOWNLOADS else f' (from {entry.relative})'))
        if entry not in used:
            used.append(entry)
    return used


def classify(process: LXCatProcess, selection: CrossSectionSelection, report: BuildReport) -> tuple[Optional[XSecKind], Optional[str], str]:
    """PICLas kind, group and dataset name of an LXCat process"""
    if process.type in selection.types:
        kind = XSecKind(selection.types[process.type])
    elif process.type in ('ELASTIC', 'EFFECTIVE'):
        kind = XSecKind(process.type)
    elif process.type == 'EXCITATION':
        kind = excitation_kind(process)
    elif process.type == 'IONIZATION':
        kind = XSecKind.REACTION
    elif process.type.lower() in ION_NEUTRAL_TYPES:
        kind = ION_NEUTRAL_TYPES[process.type.lower()]
    else:
        report.notes.append(f'{process.species}: {process.process}: type {process.type} not supported, skipped (map it with "types")')
        return None, None, ''
    if kind is XSecKind.REACTION:
        return kind, 'REACTION', '-'.join(products(process.process))
    if kind in (XSecKind.ELASTIC, XSecKind.EFFECTIVE, XSecKind.BACKSCATTER):
        return kind, None, kind.value
    return kind, kind.value, ''


def add_atct(species: Species, entry: StoreEntry, own: dict, report: BuildReport) -> None:
    """HeatOfFormation_K (298.15 K / R, ion convention as ATcT) and MassIC from an ATcT record; values in the recipe take precedence"""
    from piclas_db.sources.atct import parse_atct  # noqa: PLC0415

    record = parse_atct(entry.path.read_text(encoding='utf-8'))[0]
    taken = []
    if 'HeatOfFormation_K' not in own and record.heat_of_formation_k is not None:
        species.attributes['HeatOfFormation_K'] = record.heat_of_formation_k
        taken.append('HeatOfFormation_K')
    if 'MassIC' not in own and record.mass_kg is not None:
        species.attributes['MassIC'] = record.mass_kg
        taken.append('MassIC')
    for key, value in (('HeatOfFormation_K', record.heat_of_formation_k), ('MassIC', record.mass_kg)):
        if key in own and value is not None:
            # own data or recipe take precedence: say so, the value usually belongs to ATcT (e.g. masses of one consistent source)
            report.notes.append(f'{species.name}: {key} from the own data or recipe ({own[key]}), not from ATcT {record.atct_id} ({value:.10g})')
    ion = re.search(r'Ion(\d+)$', species.name)
    expected = int(ion.group(1)) if ion else (-1 if species.name == 'electron' else 0)
    if record.charge != expected:
        report.notes.append(f'{species.name}: ATcT {record.atct_id} ({record.formula}) has charge {record.charge}, the name suggests {expected}')
    if not record.gas:
        report.notes.append(f'{species.name}: ATcT {record.atct_id} is not a gas-phase species ({record.formula})')
    reference = f'ATcT {record.version} ({record.atct_id}, {record.formula}): ' + ', '.join(taken)
    species.provenance.reference = '; '.join(filter(None, [species.provenance.reference, reference]))
    species.provenance.extra = {**species.provenance.extra, **source_provenance(entry)}


def lxcat_database(file: LXCatFile, path: str) -> Database:
    """All processes of an LXCat download (TXT, XML or ZIP) as a database (for plot and diff of original files)"""
    database = Database(path=path, schema=Schema.SPECIES_DATABASE)
    report = BuildReport()
    groups: dict[tuple[str, str], list[LXCatProcess]] = {}
    for process in file.processes:
        groups.setdefault((process.database, process.species), []).append(process)
    for (name, species), processes in groups.items():
        pair_name = f'{piclas_name(processes[0].target)}-{piclas_name(processes[0].projectile)}'
        pair = database.collision_pairs.setdefault(pair_name, CollisionPair(name=pair_name))
        selection = CrossSectionSelection(source=Requirement('lxcat', 'file'), species=species, database=name)
        for process in processes:
            kind, group, key = classify(process, selection, report)
            if kind is None:
                continue
            value = threshold(process)
            if group in ('ROTATION', 'VIBRATION', 'ELECTRONIC'):
                if value is None:
                    continue
                key = str(value)
            if any(existing.group == group and existing.key == key for existing in pair.cross_sections):
                continue
            provenance = Provenance(reference=reference(file, process.database), info=info(process))
            pair.cross_sections.append(CrossSection(kind=kind, key=key, data=process.data.copy(), group=group, threshold=value, provenance=provenance))
    return database


def nist_database(text: str, path: str, species: Optional[str] = None) -> Database:
    """Electronic levels of a NIST ASD export as a database (for plot and diff of original files)"""
    parsed = parse_nist_levels(text, name_hint=path)
    name = species or parsed.species
    if not name:
        raise BuildError(f'{path}: species of the NIST ASD file unknown')
    factor = {'cm-1': CM_TO_K, 'eV': EV_TO_K, 'Ry': RYDBERG_EV * EV_TO_K}[parsed.unit]
    levels = parsed.levels.copy()
    levels[:, 1] *= factor
    database = Database(path=path, schema=Schema.LEGACY_ELECTRONIC)
    database.species[name] = Species(name=name, electronic_levels=levels[np.argsort(levels[:, 1], kind='stable')])
    database.species[name].provenance.reference = 'NIST Atomic Spectra Database'
    return database


# ----------------------------------------------------------------------------------------------------------------------------------
# Electronic levels
# ----------------------------------------------------------------------------------------------------------------------------------
def add_levels(database: Database, selection: LevelSelection, entry: StoreEntry, report: BuildReport) -> None:
    parsed = parse_nist_levels(entry.path.read_text(encoding='utf-8', errors='replace'), name_hint=entry.path.name)
    factor = {'cm-1': CM_TO_K, 'eV': EV_TO_K, 'Ry': RYDBERG_EV * EV_TO_K}[parsed.unit]
    levels = parsed.levels.copy()
    label = f'{selection.species} ({entry.relative})'
    if parsed.estimated and not selection.estimated:
        # theoretical or derived energies stay in the store (the original file) but not in the database unless asked for
        bound = parsed.levels[:, 1] < parsed.limit if parsed.limit is not None else np.ones(len(parsed.levels), dtype=bool)
        theoretical = int((parsed.estimated_mask & bound).sum())
        levels = levels[~parsed.estimated_mask]
        report.notes.append(f'{label}: {parsed.estimated} levels with energies in brackets (theoretical or derived) left out (estimated: false)')
        if theoretical > 0.5 * int(bound.sum()):
            # e.g. He I, H-like ions: NIST ASD gives (accurate) theoretical values for most levels
            report.notes.append(f'WARNING {label}: {theoretical} of {int(bound.sum())} bound levels are theoretical; without them {int(bound.sum()) - theoretical} remain (estimated: false)')
    if parsed.limit is None:
        report.notes.append(f'{label}: no ionization limit in the file, all {len(levels)} levels kept and no limit level added')
    else:
        # PICLas convention: the bound levels, then the ionization limit as last level with degeneracy 1 (PICLas takes the last
        # level as ionization energy, e.g. for QK ionization and the heat of formation of the ion)
        above = levels[:, 1] >= parsed.limit
        if above.any():
            report.notes.append(f'{label}: {int(above.sum())} levels at or above the ionization limit ({parsed.limit:.10g} {parsed.unit}) left out')
        levels = np.vstack([levels[~above], [[1.0, parsed.limit]]])
    if parsed.doubtful:
        report.notes.append(f'{label}: {parsed.doubtful} levels with relative (+x) or doubtful (?) energies left out')
    if parsed.estimated and selection.estimated:
        report.notes.append(f'{label}: {parsed.estimated} levels with energies in brackets (theoretical or derived values in NIST ASD) included')
    levels[:, 1] *= factor
    levels = levels[np.argsort(levels[:, 1], kind='stable')]
    species = database.species.setdefault(selection.species, Species(name=selection.species))
    species.electronic_levels = levels
    retrieved = entry.meta.get('retrieved')
    species.provenance.reference = 'NIST Atomic Spectra Database (https://physics.nist.gov/asd)' + (f', retrieved on {retrieved}' if retrieved else '')
    species.provenance.extra.update(source_provenance(entry))
    limit = '' if parsed.limit is None else ', the last one the ionization limit'
    report.added.append(f'/Species/{selection.species}/ElectronicLevel ({len(levels)} levels{limit}, converted from {parsed.unit} to K)')


# ----------------------------------------------------------------------------------------------------------------------------------
# Literature
# ----------------------------------------------------------------------------------------------------------------------------------
def literature_part(entry: StoreEntry, label: str, allow_unreviewed: bool) -> tuple[np.ndarray, dict, str]:
    """Data (eV, m^2), record and review status of one stored extraction; refuses unreviewed (unless allowed) and rejected ones"""
    from piclas_db.literature import read_extraction  # noqa: PLC0415

    record = entry.meta.get('extraction') or {}
    status = (record.get('review') or {}).get('status', 'pending')
    if status == 'rejected' or (status != 'approved' and not allow_unreviewed):
        raise BuildError(f'{label}: extraction is {status} (review it with piclas-db literature review, or build with --allow-unreviewed)')
    return read_extraction(entry), record, status


def citation(record: dict) -> str:
    source = record.get('source') or {}
    where = ', '.join(f'{label} {source[label]}' for label in ('table', 'figure', 'equation', 'page') if source.get(label))
    return f'{source.get("reference") or source.get("doi")}' + (f' (doi:{source["doi"]})' if source.get('doi') and source.get('reference') else '') + f', {where}'


def add_literature(database: Database, selection: LiteratureSelection, entries: dict[str, Optional[StoreEntry]], report: BuildReport, allow_unreviewed: bool) -> None:
    kind = XSecKind(selection.kind)
    group = None if kind in (XSecKind.ELASTIC, XSecKind.EFFECTIVE, XSecKind.BACKSCATTER) else kind.value
    key = kind.value if group is None else (str(selection.key) if kind is XSecKind.REACTION else str(selection.threshold))
    pair = database.collision_pairs.setdefault(selection.pair, CollisionPair(name=selection.pair))
    name = f'/Cross-Sections/{selection.pair}/' + (f'{group}/' if group else '') + key
    if any(existing.group == group and existing.key == key for existing in pair.cross_sections):
        report.notes.append(f'{selection.pair}: {group + "/" if group else ""}{key} exists already, {selection.source} skipped')
        return
    parts = selection.parts or [(selection.source, None)]
    pieces, records, statuses, full_data = [], [], [], []
    for requirement, limits in parts:
        entry = entries[str(requirement)]
        assert entry is not None
        data, record, status = literature_part(entry, str(requirement), allow_unreviewed)
        full_data.append(data)
        if limits is not None:
            data = data[(data[:, 0] >= limits[0]) & (data[:, 0] <= limits[1])]
            if len(data) == 0:
                raise BuildError(f'{requirement}: no data in the range {limits[0]:g}-{limits[1]:g} eV')
        pieces.append((requirement, data))
        records.append((entry, record))
        statuses.append(status)
    data = np.vstack([piece for _, piece in pieces])
    # seams between parts: how well the two sources agree there (not the rise of sigma between neighbouring points)
    from piclas_db.plot import seam_mismatch  # noqa: PLC0415

    for index, ((first, left), (second, right)) in enumerate(itertools.pairwise(pieces)):
        _, relative, how = seam_mismatch(full_data[index], full_data[index + 1], float(left[-1, 0]), float(right[0, 0]))
        report.notes.append(f'{name}: seam {left[-1, 0]:g} -> {right[0, 0]:g} eV between {first} and {second}: sources differ by {relative:+.1%} ({how})')
    report.combined[name] = [(str(requirement), full) for (requirement, _), full in zip(parts, full_data, strict=True)]
    if selection.zero_at is not None and data[0, 0] > selection.zero_at:
        data = np.vstack([[selection.zero_at, 0.0], data])
    review = 'approved' if all(status == 'approved' for status in statuses) else ('pending' if 'pending' in statuses else statuses[0])
    provenance = Provenance(
        reference='; '.join(dict.fromkeys(citation(record) for _, record in records)),
        info=' + '.join(str((record.get('quantity') or {}).get('description')) for _, record in records),
        extra={
            '* Source': '; '.join(str(source_provenance(entry)['* Source']) for entry, _ in records),
            '* Extraction': '; '.join(f'{record.get("method")} by {(record.get("created") or {}).get("by") or "unknown"} with {(record.get("created") or {}).get("tool")}' for _, record in records),
            '* Review': '; '.join(
                f'{status}' + (f' by {(record.get("review") or {}).get("reviewer")}, {(record.get("review") or {}).get("date")}' if status != 'pending' else '')
                for (_, record), status in zip(records, statuses, strict=True)
            ),
            **({'* Parts': '; '.join(f'{requirement}: {limits[0]:g}-{limits[1]:g} eV' for requirement, limits in parts if limits)} if selection.parts else {}),
            **({'* Zero at': f'{selection.zero_at:g} eV (inserted)'} if selection.zero_at is not None else {}),
        },
    )
    pair.cross_sections.append(CrossSection(kind=kind, key=key, data=data, group=group, threshold=selection.threshold, provenance=provenance))
    report.added.append(f'{name} (from {" + ".join(str(requirement) for requirement, _ in parts)}, review {review})')


# ----------------------------------------------------------------------------------------------------------------------------------
# Build
# ----------------------------------------------------------------------------------------------------------------------------------
def build(recipe: Recipe, resolutions: list[Resolution], allow_unreviewed: bool = False, store: Optional[Store] = None) -> tuple[Database, BuildReport]:
    """Assemble the database; all requirements must have been resolved to files in the store"""
    missing = [str(resolution.requirement) for resolution in resolutions if resolution.origin is Origin.MANUAL or resolution.entry is None]
    if missing:
        raise BuildError('original files missing in the store: ' + ', '.join(missing))
    entries = {str(resolution.requirement): resolution.entry for resolution in resolutions}

    database = Database(path=recipe.path, schema=Schema.SPECIES_DATABASE)
    report = BuildReport()
    index: Optional[list[Found]] = None
    for selection in recipe.cross_sections:
        if selection.source.dataset == ALL_DOWNLOADS:
            if store is None:
                raise BuildError('"source: lxcat" needs the store')
            index = index if index is not None else lxcat_index(store)
            found = index
        else:
            entry = entries[str(selection.source)]
            assert entry is not None
            file = load_lxcat(entry.path)
            found = [(process, file, entry) for process in file.processes]
        for used in add_cross_sections(database, selection, found, report):
            if used not in report.files:
                report.files.append(used)
    for literature_selection in recipe.literature:
        add_literature(database, literature_selection, entries, report, allow_unreviewed)
    for level_selection in recipe.levels:
        entry = entries[str(level_selection.source)]
        assert entry is not None
        add_levels(database, level_selection, entry, report)
    own_files = []
    for requirement in recipe.own_data:
        entry = entries[str(requirement)]
        assert entry is not None
        from piclas_db.sources.own import parse_own_data  # noqa: PLC0415

        own_files.append((entry, parse_own_data(entry.path.read_text(encoding='utf-8'))))
    for name, attributes in recipe.species.items():
        species = database.species.setdefault(name, Species(name=name))
        own = {key: value for key, value in (attributes or {}).items() if key != 'atct'}
        if own:
            # values in the recipe are not in the store: fine for tests, but the data belong into an own-data file
            report.notes.append(f'{name}: {", ".join(sorted(own))} written in the recipe, not in the store (move them into an own-data file)')
        stored = next(((entry, content['species'][name]) for entry, content in own_files if name in content['species']), None)
        if stored is not None:
            entry, values = stored
            for key, value in values.items():
                if key == 'Reference':
                    species.provenance.reference = '; '.join(filter(None, [species.provenance.reference, str(value)]))
                elif key in LEVEL_KEYS:
                    current = species.electronic_levels if key == 'ElectronicLevel' else species.vibrational_levels
                    if current is not None:
                        report.notes.append(f'{name}: {key} of the own data not used, the levels of the recipe are')
                    elif key == 'ElectronicLevel':
                        species.electronic_levels = level_array(key, value)
                    else:
                        species.vibrational_levels = level_array(key, value)
                elif key not in own:
                    species.attributes[key] = value
            species.provenance.extra = {**species.provenance.extra, **source_provenance(entry)}
        elif own_files:
            report.notes.append(f'{name}: not in the own data ({", ".join(entry.relative for entry, _ in own_files)})')
        if (attributes or {}).get('atct'):
            from piclas_db.recipe import atct_requirement  # noqa: PLC0415

            atct_entry = entries[str(atct_requirement(str(attributes['atct'])))]
            assert atct_entry is not None
            add_atct(species, atct_entry, {**own, **{k: v for k, v in (stored[1] if stored else {}).items() if k != 'Reference'}}, report)
        species.attributes.update(own)
        origin = ['own data'] * (stored is not None) + ['ATcT'] * bool((attributes or {}).get('atct')) + ['recipe'] * bool(own)
        report.added.append(f'/Species/{name} ({", ".join(origin) or "no values"})')
    if recipe.masses == 'composition' or recipe.charges == 'name':
        from piclas_db.derive import derive_charges, derive_masses  # noqa: PLC0415

        if recipe.masses == 'composition':
            derive_masses(database, recipe.species, report.notes)
        if recipe.charges == 'name':
            derive_charges(database, recipe.species, report.notes)
    for name, attributes in recipe.reactions.items():
        database.reactions[name] = Reaction(name=name, attributes=dict(attributes), provenance=Provenance(reference=f'recipe {recipe.path}'))
        report.added.append(f'/Reactions/{name} (from the recipe)')
    return database, report
