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
"""Where the data of an existing database come from: every cross-section compared point by point with everything in the store

Candidates are the processes of all LXCat downloads, all extractions from papers (tables, figures) and all fit formulas. A point of a
dataset is explained by a candidate if the candidate has the same energy and the same cross-section (to float32 precision, as old
databases are often float32); formulas are evaluated at the energies of the dataset. Extractions given over the laboratory energy are
also tried over the laboratory energy: a match there means that the dataset uses the laboratory energy (PICLas expects the collision
energy). A dataset is

* complete:  all points (apart from sigma = 0 at a threshold) from one candidate
* combined:  all points from several candidates, each in an energy range
* partial:   some points explained, others not
* unknown:   no point explained (the source is not in the store yet)
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import numpy as np

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.build import lxcat_index, piclas_name
from piclas_db.compare import canonical_pair
from piclas_db.model import CrossSection, Database
from piclas_db.store import Store
# ==================================================================================================================================

RTOL = 1.0e-6  # float32 has about 7 significant digits
MIN_POINTS = 3  # points a candidate must explain to count


@dataclass
class Candidate:
    name: str  # e.g. 'lxcat Biagi-v7.1 e / Ar: E + Ar -> E + E + Ar+, Ionization' or 'literature/yoon-2008/table13-c1'
    kind: str  # 'lxcat', 'table', 'formula'
    data: Optional[np.ndarray] = None  # eV, m^2 (tables, LXCat)
    function: Optional[Callable[[np.ndarray], np.ndarray]] = None  # formulas: sigma [m^2] at energies [eV]
    low: float = 0.0
    high: float = float('inf')
    note: str = ''  # e.g. 'over the laboratory energy'
    reference: dict[str, str] = field(default_factory=dict)  # for the recipe draft: source, database, species, process
    pair: str = ''  # collision pair in PICLas names if known (LXCat species, assignment of an extraction); '' = any pair

    def explains(self, energies: np.ndarray, sigmas: np.ndarray) -> np.ndarray:
        """Which points (energy, sigma) this candidate gives exactly"""
        if self.function is not None:
            inside = (energies >= self.low * (1 - RTOL)) & (energies <= self.high * (1 + RTOL))
            with np.errstate(all='ignore'):
                values = np.where(inside, self.function(np.where(inside, energies, self.low)), np.nan)
            return inside & np.isclose(values, sigmas, rtol=RTOL * 10, atol=1.0e-40) & (sigmas > 0.0)
        assert self.data is not None
        result = np.zeros(len(energies), dtype=bool)
        for index, (energy, sigma) in enumerate(zip(energies, sigmas, strict=True)):
            if not sigma > 0.0:
                continue  # zeros (thresholds) are in many sources and prove nothing
            same = np.isclose(self.data[:, 0], energy, rtol=RTOL, atol=0.0) & np.isclose(self.data[:, 1], sigma, rtol=RTOL, atol=1.0e-40)
            result[index] = bool(np.any(same))
        return result


@dataclass
class Part:
    candidate: Candidate
    low: float
    high: float
    points: int


@dataclass
class Explanation:
    path: str  # /Cross-Sections/<pair>/[group/]key
    pair: str
    xsec: CrossSection
    status: str  # complete, combined, partial, unknown
    parts: list[Part] = field(default_factory=list)
    zero_at: Optional[float] = None
    unexplained: list[tuple[float, float]] = field(default_factory=list)


# ----------------------------------------------------------------------------------------------------------------------------------
# Candidates from the store
# ----------------------------------------------------------------------------------------------------------------------------------
def candidates(store: Store) -> list[Candidate]:
    from piclas_db.formula import FormulaError, compile_formula  # noqa: PLC0415
    from piclas_db.literature import AREA_UNITS, ENERGY_UNITS, LiteratureError, energy_frame, extractions, read_extraction, unit_factor  # noqa: PLC0415

    found: list[Candidate] = []
    for process, _, entry in lxcat_index(store):
        name = f'lxcat {process.database.split(" ")[0]} {process.species}: {process.process}'
        found.append(
            Candidate(
                name=name,
                kind='lxcat',
                data=process.data,
                reference={'source': 'lxcat', 'database': process.database.split(' ')[0], 'species': process.species, 'process': process.process, 'file': entry.relative},
                pair=canonical_pair(f'{piclas_name(process.target)}-{piclas_name(process.projectile)}'),
            )
        )
    for entry in extractions(store):
        record = entry.meta.get('extraction') or {}
        if record.get('parameter_table'):
            continue
        dataset = f'literature/{entry.meta.get("dataset")}'
        columns = record.get('columns') or {}
        energy = columns.get('energy') or {}
        lab = energy_frame(energy) == 'lab' and isinstance(energy.get('mass_amu'), (int, float)) and isinstance(energy.get('target_mass_amu'), (int, float))
        factor = (float(energy['mass_amu']) + float(energy['target_mass_amu'])) / float(energy['target_mass_amu']) if lab else 1.0  # E_lab / E_cm
        reference = {'source': dataset}
        assigned = str(((record.get('quantity') or {}).get('assignment') or {}).get('pair') or '')
        pair = canonical_pair(assigned) if assigned else ''
        try:
            if record.get('formula'):
                formula = record['formula']
                function = compile_formula(str(formula['expression']), {str(k): float(v) for k, v in (formula.get('parameters') or {}).items()})
                to_ev = unit_factor(str(energy.get('unit', 'eV')), ENERGY_UNITS)
                to_m2 = unit_factor(str((columns.get('cross_section') or {}).get('unit', '1e-16 cm^2')), AREA_UNITS)
                threshold = float(formula['threshold']) * to_ev if formula.get('threshold') is not None else None
                low, high = (float(value) * to_ev for value in formula['range'])

                def evaluate(collision: np.ndarray, frame: float, function: Callable = function, to_ev: float = to_ev, to_m2: float = to_m2, threshold: Optional[float] = threshold) -> np.ndarray:
                    printed = collision * frame / to_ev  # energy as used in the formula (laboratory if frame > 1)
                    values = function(printed) * to_m2
                    return np.where(threshold is not None and collision * frame <= threshold, 0.0, values) if threshold is not None else values

                found.append(Candidate(dataset, 'formula', function=lambda e, ev=evaluate, f=factor: ev(e, f), low=low / factor, high=high / factor, reference=reference, pair=pair))
                if lab:
                    found.append(Candidate(dataset, 'formula', function=lambda e, ev=evaluate: ev(e, 1.0), low=low, high=high, note='over the laboratory energy', reference=reference, pair=pair))
            else:
                data = read_extraction(entry)
                found.append(Candidate(dataset, 'table', data=data, reference=reference, pair=pair))
                if lab:
                    found.append(Candidate(dataset, 'table', data=np.column_stack([data[:, 0] * factor, data[:, 1]]), note='over the laboratory energy', reference=reference, pair=pair))
        except (FormulaError, LiteratureError, KeyError, TypeError, ValueError):
            continue
    return found


# ----------------------------------------------------------------------------------------------------------------------------------
# Explanation of one dataset and of a database
# ----------------------------------------------------------------------------------------------------------------------------------
def explain_dataset(path: str, pair: str, xsec: CrossSection, pool: list[Candidate]) -> Explanation:
    data = xsec.data
    energies, sigmas = data[:, 0], data[:, 1]
    lowest, highest = float(np.min(energies)), float(np.max(energies))
    origin: list[Optional[Candidate]] = [None] * len(data)
    # candidates that overlap the energy range; the one explaining most points first (greedy cover)
    remaining = np.ones(len(data), dtype=bool)
    useful = []
    for candidate in pool:
        if candidate.pair and candidate.pair != canonical_pair(pair):
            continue  # data of other species
        if candidate.data is not None and (candidate.data[-1, 0] < lowest * (1 - RTOL) or candidate.data[0, 0] > highest * (1 + RTOL)):
            continue
        hits = candidate.explains(energies, sigmas)
        own = int((candidate.data[:, 1] > 0.0).sum()) if candidate.data is not None else MIN_POINTS
        if hits.sum() >= min(MIN_POINTS, int((sigmas > 0.0).sum()), own):  # a single equal number can be a coincidence
            useful.append((candidate, hits))
    while useful:
        candidate, hits = max(useful, key=lambda item: int((item[1] & remaining).sum()))
        new = hits & remaining
        if not new.any():
            break
        for index in np.flatnonzero(new):
            origin[index] = candidate
        remaining &= ~new
        useful = [item for item in useful if item[0] is not candidate]
    parts: list[Part] = []
    for index, candidate in enumerate(origin):
        if candidate is None:
            continue
        if parts and parts[-1].candidate is candidate:
            parts[-1].high = float(energies[index])
            parts[-1].points += 1
        else:
            parts.append(Part(candidate, float(energies[index]), float(energies[index]), 1))
    unexplained = [(float(e), float(s)) for (e, s), candidate in zip(data.tolist(), origin, strict=True) if candidate is None]
    zero_at = None
    if unexplained and not unexplained[0][1] > 0.0 and unexplained[0][0] <= lowest:
        zero_at = unexplained.pop(0)[0]  # sigma = 0 at the threshold: part of the recipe, not of a source
    if not parts:
        status = 'unknown'
    elif unexplained:
        status = 'partial'
    else:
        status = 'complete' if len({id(part.candidate) for part in parts}) == 1 else 'combined'
    return Explanation(path, pair, xsec, status, parts, zero_at, unexplained)


def explain_database(database: Database, pool: list[Candidate]) -> list[Explanation]:
    results = []
    for pair in sorted(database.collision_pairs.values(), key=lambda p: p.name):
        for xsec in pair.cross_sections:
            if xsec.data.ndim != 2 or len(xsec.data) == 0:
                continue
            path = f'/Cross-Sections/{pair.name}/' + (f'{xsec.group}/' if xsec.group else '') + xsec.key
            results.append(explain_dataset(path, pair.name, xsec, pool))
    return results


# ----------------------------------------------------------------------------------------------------------------------------------
# Report and recipe draft
# ----------------------------------------------------------------------------------------------------------------------------------
def summary(results: list[Explanation]) -> str:
    counts = {status: sum(1 for result in results if result.status == status) for status in ('complete', 'combined', 'partial', 'unknown')}
    lab = sum(1 for result in results if any(part.candidate.note for part in result.parts))
    return f'{len(results)} cross-sections: {counts["complete"]} complete, {counts["combined"]} combined, {counts["partial"]} partial, {counts["unknown"]} without source in the store' + (
        f'; {lab} over the laboratory energy' if lab else ''
    )


def describe(result: Explanation) -> list[str]:
    lines = [f'{result.path}: {result.status} ({len(result.xsec.data)} points)']
    lines.extend(f'    {part.low:g}-{part.high:g} eV  {part.points:4d} points  {part.candidate.name}' + (f'  ** {part.candidate.note} **' if part.candidate.note else '') for part in result.parts)
    if result.zero_at is not None:
        lines.append(f'    sigma = 0 at {result.zero_at:g} eV')
    if result.unexplained:
        lines.append(f'    not explained: {len(result.unexplained)} point(s), ' + ', '.join(f'{e:g} eV' for e, _ in result.unexplained[:4]) + (' ...' if len(result.unexplained) > 4 else ''))
    return lines


def report(source: str, results: list[Explanation]) -> str:
    """Markdown report: one table row per cross-section"""
    lines = [f'# Sources of {source}', '', summary(results), '', '| Dataset | Status | Points | Sources (energy range) | Not explained |', '| --- | --- | --- | --- | --- |']
    for result in results:
        parts = '<br>'.join(f'{part.candidate.name} ({part.low:g}–{part.high:g} eV, {part.points})' + (f' **{part.candidate.note}**' if part.candidate.note else '') for part in result.parts)
        if result.zero_at is not None:
            parts += f'<br>σ = 0 at {result.zero_at:g} eV'
        missing = f'{len(result.unexplained)}' if result.unexplained else ''
        lines.append(f'| `{result.path}` | {result.status} | {len(result.xsec.data)} | {parts or "–"} | {missing} |')
    lines += ['', 'A dataset over the **laboratory energy** matches its source only if the energies are not converted to the collision energy PICLas uses.']
    return '\n'.join(lines) + '\n'


def short(value: float) -> float:
    """7 significant digits: float32 values of old databases (15.399999618530273) written as they were meant (15.4)"""
    return float(f'{value:.7g}')


def recipe_draft(source: str, results: list[Explanation]) -> str:
    """Recipe that rebuilds the explained datasets: LXCat processes grouped by pair, database and species; papers with their parts"""
    import yaml  # noqa: PLC0415

    lxcat: dict[tuple[str, str, str], list[str]] = {}
    literature = []
    comments = []
    for result in results:
        key = result.xsec.key
        kind = result.xsec.group or result.xsec.kind.value
        if result.status in ('unknown', 'partial'):
            comments.append(f'# {result.path}: {result.status}, not in the recipe' + (f' ({len(result.unexplained)} point(s) without source)' if result.unexplained else ''))
            continue
        if all(part.candidate.kind == 'lxcat' for part in result.parts) and len(result.parts) == 1:
            reference = result.parts[0].candidate.reference
            lxcat.setdefault((result.pair, reference['database'], reference['species']), []).append(reference['process'].split(',')[0].strip())
            continue
        if any(part.candidate.note for part in result.parts):
            comments.append(f'# {result.path}: source matches only over the laboratory energy; rebuilt over the collision energy it will differ')
        entry: dict[str, object] = {'pair': result.pair, 'kind': kind if kind in ('REACTION', 'ELECTRONIC', 'VIBRATION', 'ROTATION') else result.xsec.kind.value}
        if entry['kind'] == 'REACTION':
            entry['key'] = key
        elif entry['kind'] in ('ELECTRONIC', 'VIBRATION', 'ROTATION'):
            entry['threshold'] = float(key)
        if len(result.parts) == 1:
            entry = {'source': result.parts[0].candidate.reference['source'], **entry}
        else:
            entry = {'parts': [{'source': part.candidate.reference['source'], 'range': [short(part.low), short(part.high)]} for part in result.parts], **entry}
        if result.zero_at is not None:
            entry['zero_at'] = short(result.zero_at)
        literature.append(entry)
    content: dict[str, object] = {'description': f'Draft recipe derived from the numbers of {source} (piclas-db rebuild --explain); check before use'}
    if lxcat:
        content['cross_sections'] = [{'source': 'lxcat', 'database': database, 'species': species, 'pair': pair, 'processes': sorted(set(processes))} for (pair, database, species), processes in sorted(lxcat.items())]
    if literature:
        content['literature'] = literature
    return yaml.safe_dump(content, sort_keys=False, allow_unicode=True, width=1000) + ('\n'.join(comments) + '\n' if comments else '')
