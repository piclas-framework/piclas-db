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
import argparse
import importlib.metadata
import itertools
import operator
import pathlib
from typing import Any, Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import numpy as np
import yaml

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.extract.raster import RESOLUTION, SCALE, extract_raster, grid_image, is_scanned, raster_figure_frames
from piclas_db.extract.table import ARROWS, Table, extract_table, header_unit, parse_number
from piclas_db.extract.vector import ExtractError, extract, figure_frames, require_pdfplumber, review_image, tesseract_version, values
from piclas_db import config
from piclas_db.common.common_vars import Common
from piclas_db.literature import LiteratureError, papers, template
from piclas_db.sources.identify import slug
from piclas_db.store import Store, StoreEntry
# ==================================================================================================================================


def numbers(text: Optional[str]) -> Optional[list[float]]:
    return [float(part) for part in text.split(',')] if text else None


def seed_points(text: Optional[str]) -> Optional[list[tuple[float, ...]]]:
    """'x,y;x,y,x2,y2': one or two points per curve"""
    if not text:
        return None
    seeds = [tuple(float(value) for value in group.split(',')) for group in text.split(';')]
    if any(len(seed) not in (2, 4) for seed in seeds):
        raise ValueError('--seeds: one or two points (x,y or x,y,x2,y2) per curve, curves separated by ";"')
    return seeds


def pairs(text: Optional[str], separator: str) -> Optional[list[tuple[float, float]]]:
    """'a=b,c=d' (calibration points, coordinate=value) or 'x,y;x,y' (seed points)"""
    if not text:
        return None
    result = []
    for item in text.split(',' if separator == '=' else ';'):
        parts = item.split(separator)
        if len(parts) != 2:
            raise ValueError(f'"{item.strip()}" is not of the form pt=value (calibration points: "142.1=4,157.1=8,...", every point written out)')
        result.append((float(parts[0]), float(parts[1])))
    return result


COMMAND_OPTIONS = (
    'page', 'frame', 'figure', 'name', 'table', 'ocr', 'raster', 'symbol_radius', 'frame_box', 'x_points', 'y_points', 'seeds',
    'x_labels', 'y_labels', 'x_scale', 'y_scale', 'x_unit', 'x_quantity', 'mass_amu', 'target_mass_amu', 'energy_frame', 'y_unit', 'by',
    'rates', 'rate_unit', 'chemistry_model', 'glyphs', 'columns',
)  # fmt: skip


def command_of(args: argparse.Namespace) -> dict[str, object]:
    """Options of this extraction, stored in the record so that 'extract --redo' can run it again"""
    return {option: getattr(args, option) for option in COMMAND_OPTIONS if getattr(args, option, None) not in (None, False)}


def page_list(text: str) -> list[int]:
    """'14', '14-15' or '4,5'"""
    pages: list[int] = []
    for part in text.split(','):
        first, _, last = part.partition('-')
        pages += list(range(int(first), int(last or first) + 1))
    return pages


def column_table(args: argparse.Namespace, paper: StoreEntry, path: str, output: pathlib.Path) -> bool:
    """--rates for a reaction table with columns (C, n, T_d, Tx, third body; read character by character or by OCR, extract/reactions.py)
    when it converts more rows than the reading of the table as label, reaction and one formula cell (Farbar, Boyd, Plane); True if
    written"""
    from piclas_db import rates  # noqa: PLC0415
    from piclas_db.extract import reactions  # noqa: PLC0415

    numbers = args.table.split(',')
    try:
        positional = [role.strip() for role in (args.columns or '').split(',')] if args.columns and '=' not in args.columns else None
        if args.ocr and positional:  # a scan, cell by cell, with the role of each column given from left to right
            lines, caption, pages = scan_lines(path, page_list(args.page), numbers, positional)
        else:
            lines, caption, pages = reactions.table_lines(path, page_list(args.page), numbers, use_ocr=args.ocr, glyphs=glyph_map(args.glyphs))
        result = reactions.convert_columns(lines, None if positional else column_roles(args.columns))
    except (ExtractError, rates.RateError):
        return False
    if len(numbers) == 1 and not result.converted and not (args.ocr and positional):
        return False
    if len(numbers) == 1 and not positional and not any(len(row) > 5 for row in result.raw):  # label, reaction and one formula cell
        try:
            simple = extract_table(path, page_list(args.page), numbers[0], use_ocr=args.ocr)
            if len(rates.convert_table(simple.header, simple.rows)[0]) >= len(result.converted):
                return False
        except ExtractError:
            pass
    table = Table('-'.join(numbers), caption, pages, result.header, [row + [''] * (len(result.header) - len(row)) for row in result.raw], 'ocr' if args.ocr else 'text')
    name = slug(args.name or ('tables' if len(numbers) > 1 else 'table') + '-'.join(number.replace('.', '') for number in numbers))  # tablea1
    raw_file = output / f'{name}-raw.csv'
    import csv  # noqa: PLC0415

    with raw_file.open('w', newline='') as file:
        writer = csv.writer(file, lineterminator='\n')
        writer.writerow(table.header)
        writer.writerows(table.rows)
    print(f'table {", ".join(numbers)} (pages {", ".join(str(p) for p in pages)}, {table.source}, column table): {len(table.rows)} rows -> {raw_file}')
    print(f'  caption: {caption}')
    write_reaction_table(args, paper, table, output, name, raw_file, (result.converted, result.problems))
    return True


def scan_lines(path: str, pages: list[int], numbers: list[str], roles: list[str]) -> tuple[list, str, list[int]]:
    """Lines of a scanned reaction table, read cell by cell on every page (the header repeated on continuation pages)"""
    from piclas_db.extract import reactions  # noqa: PLC0415

    pdfplumber = require_pdfplumber()
    lines: list = []
    caption, used = '', []
    with pdfplumber.open(path) as pdf:
        for number in pages:
            page_lines, page_caption = reactions.scan_table_lines(pdf.pages[number - 1], numbers, roles)
            lines += page_lines if not lines else page_lines[1:]  # the header once
            caption = caption or page_caption
            used.append(number)
    return lines, caption, used


def glyph_map(text: Optional[str]) -> Optional[dict[str, str]]:
    """--glyphs '(cid:5)=×,þ=+': glyphs of a font without Unicode map"""
    if not text:
        return None
    result: dict[str, str] = {}
    for item in text.split(','):
        key, _, value = item.rpartition('=')
        if key:
            result[key] = value
    return result


def column_roles(text: Optional[str]) -> Optional[dict[str, str]]:
    """--columns 'Ta=Tx,Tr=Td': roles of columns by their header (C, n, Td, Tx, M, skip)"""
    if not text:
        return None
    return {key.strip(): value.strip() for key, value in (item.split('=', 1) for item in text.split(',') if '=' in item)}


def write_reaction_table(args: argparse.Namespace, paper: StoreEntry, table: Table, output: pathlib.Path, name: str, raw_file: pathlib.Path, done: Optional[tuple[list, list[str]]] = None) -> None:
    """A reaction table: the raw copy with its record (<name>-raw), and with --rates [TOPIC] the rate table converted from it
    (<name>-rates[-TOPIC]), whose record points to the raw copy"""
    from piclas_db import rates  # noqa: PLC0415
    from piclas_db.literature import rate_record  # noqa: PLC0415
    from piclas_db.store import sha256  # noqa: PLC0415

    paper_key = str(paper.meta.get('dataset'))
    pages = ', '.join(str(p) for p in table.pages)
    raw = template(paper, f'{name}-raw', pages, table.number, None, table.source)
    raw['created']['by'] = args.by
    raw['data'] = raw_file.name
    raw['raw_table'] = True
    raw['quantity'] = {'description': f'{table.caption} (raw copy as printed: cells of the reaction table, not used by builds)'}
    raw['parameters'] = {'pages': table.pages, 'table': table.number, 'command': command_of(args)}
    for key in ('columns', 'accuracy'):
        raw.pop(key, None)
    raw_record = output / f'{name}-raw.extraction.yaml'
    raw_record.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True, width=1000))
    print(f'  raw copy: {raw_record}')
    if args.rates is None and table.source == 'ocr':
        print('  scan: the OCR copy is a reading aid only (exponents, subscripts and charges are often misread; do not store it).')
        print('  Enter the table by hand from the page and check it by double entry (tutorial T6, section 4):')
        print(f'    piclas-db literature template {paper_key} {name}-rates-<mixture> --rates --page {pages} --table {table.number} -o <directory>')
        return
    if args.rates is None:
        print('  reaction table: convert it into a rate table with --rates [TOPIC] (e.g. --rates air), or enter one with')
        print(f'    piclas-db literature template {paper_key} {name}-rates --rates --page {pages} --table {table.number} -o {output}')
        print(f'  store the raw copy with: piclas-db literature add {raw_record}')
        return
    converted, problems = done or rates.convert_table(table.header, table.rows)
    rates_name = f'{name}-rates' + (f'-{slug(args.rates)}' if args.rates else '')
    (output / f'{rates_name}.csv').write_text(rates.rate_csv(converted, problems), encoding='utf-8')
    unit = args.rate_unit or rates.printed_unit(' '.join([table.caption, *table.header]))
    record = template(paper, rates_name, pages, table.number, None, table.source) | rate_record()
    record['created']['by'] = args.by
    record['data'] = f'{rates_name}.csv'
    record['columns']['rate']['unit'] = unit
    record['quantity']['assignment']['chemistry_model'] = args.chemistry_model
    record['quantity']['mixture'] = args.rates or None
    record['derived_from'] = f'literature/{paper_key}/{name}-raw@{sha256(raw_file)[:8]}'
    record['parameters'] = {'command': command_of(args)}
    notes = sorted({row.note for row in converted if row.note and 'taken as' in row.note})
    notes += [f'row {row.row}: {row.note}' for row in converted if row.note and 'taken as' not in row.note]
    notes += [f'not converted: {problem}' for problem in problems]
    if table.source == 'ocr':
        notes.insert(0, 'read by OCR from a scan: species and exponents are often misread; check every row against the page, or enter the table by hand')
    notes.append('controlling temperature not printed: entered as T (change Tx where the paper says otherwise)')
    record['notes'] = notes
    rates_record = output / f'{rates_name}.extraction.yaml'
    rates_record.write_text(yaml.safe_dump(record, sort_keys=False, allow_unicode=True, width=1000))
    print(f'  rate table: {len(converted)} row(s) converted -> {output / rates_name}.csv, record {rates_record}')
    print(f'    unit of C: {unit or "NOT FOUND: set columns.rate.unit in the record (or --rate-unit)"}; chemistry model: {args.chemistry_model or "(none; --chemistry-model, e.g. Farbar2008)"}')
    for note in notes[:-1]:
        print(f'    check: {note}')
    print('  next: check both against the page, then')
    print(f'    piclas-db literature add -n {rates_record} --compare <database.h5>')
    print(f'    piclas-db literature add {raw_record}')
    print(f'    piclas-db literature add {rates_record}')


def write_table(args: argparse.Namespace, paper: StoreEntry, table: Table, output: pathlib.Path) -> None:
    """Raw table as CSV; for tables with an energy column one series per further column (CSV as printed + extraction record)"""
    import csv  # noqa: PLC0415

    name = slug(args.name or f'table{table.number}')
    reaction = any(any(arrow in cell for arrow in ARROWS) for row in table.rows for cell in row)
    raw_file = output / f'{name}-{"raw" if reaction else "table"}.csv'
    with raw_file.open('w', newline='') as file:
        writer = csv.writer(file, lineterminator='\n')
        writer.writerow(table.header)
        writer.writerows(table.rows)
    print(f'table {table.number} (pages {", ".join(str(p) for p in table.pages)}, {table.source}): {len(table.rows)} rows, {len(table.header)} columns -> {raw_file}')
    print(f'  caption: {table.caption}')
    if reaction:
        write_reaction_table(args, paper, table, output, name, raw_file)
        return
    parsed = [parse_number(row[0]) for row in table.rows]
    energies = [value for value in parsed if value is not None]
    if len(energies) != len(parsed) or any(b <= a for a, b in itertools.pairwise(energies)):
        # parameters of fit formulas (e.g. Janev et al. 2003): stored as a parameter table, used by formulas (parameters_from)
        record = template(paper, name, ', '.join(str(p) for p in table.pages), table.number, None, table.source)
        record['created']['by'] = args.by
        record['data'] = f'{name}-table.csv'
        record['parameter_table'] = True
        record['quantity'] = {'description': f'{table.caption} (parameters, first column: row labels)'}
        record['parameters'] = {'pages': table.pages, 'table': table.number, 'command': command_of(args)}
        for key in ('columns', 'accuracy'):
            record.pop(key, None)
        (output / f'{name}.extraction.yaml').write_text(yaml.safe_dump(record, sort_keys=False, allow_unicode=True, width=1000))
        print(f'  no increasing energy column: parameter table ({", ".join(table.header[1:])}) -> {output / name}.extraction.yaml')
        print(f'  store it with piclas-db literature add {output / name}.extraction.yaml; formulas use it with parameters_from')
        return
    pdfplumber = require_pdfplumber()
    for column in range(1, len(table.header)):
        rows = [(row[0], row[column]) for row in table.rows if parse_number(row[column]) is not None]
        if len(rows) < 2:
            continue
        series = slug(f'{name}-c{column}')
        record = template(paper, series, ', '.join(str(p) for p in table.pages), table.number, None, table.source)
        record['created']['by'] = args.by
        record['columns']['energy']['unit'] = header_unit(table.header[0]) or args.x_unit
        record['columns']['cross_section']['unit'] = header_unit(table.header[column]) or args.y_unit
        record['quantity']['description'] = f'{table.caption} - column "{table.header[column]}"'
        record['accuracy']['extraction'] = 'exact (text layer of the PDF)' if table.source == 'text' else 'OCR: compare every value with the paper'
        record['environment']['pdfplumber'] = pdfplumber.__version__
        if table.source == 'ocr':
            record['environment']['tesseract'] = tesseract_version() or 'unknown'
        record['parameters'] = {'pages': table.pages, 'table': table.number, 'column': column, 'header': table.header[column], 'command': command_of(args)}
        record['result'] = {'rows': len(rows)}
        lines = [f'# table {table.number}, column {column}: {table.header[column]}', 'energy,cross_section'] + [f'{parse_number(e)!r},{parse_number(v)!r}' for e, v in rows]
        (output / f'{series}.csv').write_text('\n'.join(lines) + '\n')
        (output / f'{series}.extraction.yaml').write_text(yaml.safe_dump(record, sort_keys=False, allow_unicode=True, width=1000))
        units = f'{record["columns"]["energy"]["unit"]}, {record["columns"]["cross_section"]["unit"]}'
        print(f'  column {column}: {len(rows)} values ({units}) -> {output / series}.csv')
    print(f'Check the records against the paper, then: piclas-db literature add {output}/<series>.extraction.yaml')


def legacy_command(record: dict) -> dict[str, object]:
    """Options of an extraction stored before 0.21.0 (no 'command' in the record), as far as the record tells them"""
    parameters, source, columns = record.get('parameters') or {}, record.get('source') or {}, record.get('columns') or {}
    energy = columns.get('energy') or {}
    command: dict[str, object] = {
        'x_unit': energy.get('unit', 'eV'),
        'y_unit': (columns.get('cross_section') or {}).get('unit', '1e-16 cm^2'),
        **{key: energy[field] for key, field in (('mass_amu', 'mass_amu'), ('target_mass_amu', 'target_mass_amu'), ('energy_frame', 'frame')) if field in energy},
    }
    if 'table' in parameters:
        command.update({'page': ','.join(str(p) for p in parameters.get('pages', [])), 'table': str(parameters['table']), 'ocr': record.get('method') == 'ocr'})
        command['name'] = str(record['name']).rsplit('-c', 1)[0]
        return command
    command.update({'page': str(parameters.get('page')), 'frame': int(parameters.get('frame', 0)), 'figure': source.get('figure')})
    command['name'] = str(record['name'])[: -len(slug(str(parameters.get('series', '')))) - 1] if parameters.get('series') else None
    for key in ('frame_box', 'seeds', 'x_points', 'y_points'):
        if parameters.get(f'{key}_pt' if key == 'frame_box' else key):
            command[key] = parameters.get(f'{key}_pt' if key == 'frame_box' else key)
    for axis in ('x', 'y'):
        calibration = (record.get('calibration') or {}).get(axis) or {}
        if calibration.get('labels_from') == 'given':
            labels = sorted(calibration.get('labels', []), key=operator.itemgetter(0), reverse=axis == 'y')  # from the origin
            command[f'{axis}_labels'] = ','.join(f'{value:g}' for _, value in labels)
        command[f'{axis}_scale'] = calibration.get('scale')
    return command


def compare_tables(old: Any, new: Any) -> str:
    """Point-by-point comparison of two extractions in axis units; relative changes only where the value is significant (values
    near zero, e.g. a measured zero, would give meaningless percentages)"""
    if len(old.energy) != len(new.energy):
        return f'{len(old.energy)} -> {len(new.energy)} points'
    if np.array_equal(new.energy, old.energy) and np.array_equal(new.cross_section, old.cross_section):
        return f'{len(old.energy)} points, identical'
    dx = float(np.max(np.abs(new.energy - old.energy)))
    change = np.abs(new.cross_section - old.cross_section)
    significant = np.abs(old.cross_section) > 0.01 * float(np.max(np.abs(old.cross_section)))
    relative = float(np.max(change[significant] / np.abs(old.cross_section[significant]))) if np.any(significant) else 0.0
    return f'{len(old.energy)} points, largest change {dx:.3g} in x and {float(np.max(change)):.3g} in y (axis units), {relative:.2%} relative'


def redo(args: argparse.Namespace) -> int:
    """Run a stored extraction again with this version of piclas-db and compare the result with the stored one"""
    from piclas_db.literature import find_extraction, read_raw, validate  # noqa: PLC0415

    store = Store(args.store)
    try:
        entry = find_extraction(store, args.redo)
        record = entry.meta.get('extraction') or {}
        if record.get('formula') or record.get('method') == 'manual':
            raise LiteratureError(f'{args.redo} was entered by hand ({record.get("method")}): nothing to run again')
        command = (record.get('parameters') or {}).get('command') or legacy_command(record)
    except LiteratureError as e:
        print(f'ERROR: {e}')
        return 1
    options = {option: getattr(args, option) for option in COMMAND_OPTIONS}
    options.update({key: value for key, value in command.items() if key in COMMAND_OPTIONS})
    rerun = argparse.Namespace(**{**vars(args), **options, 'paper': (record.get('source') or {}).get('paper'), 'redo': None, 'list': False})
    print(f'Running {args.redo} again ({record.get("method")}, stored with {record.get("created", {}).get("tool")}) with piclas-db {Common().version}:')
    if run(rerun) != 0:
        return 1
    output = pathlib.Path(args.output)
    record_file = output / f'{record["name"]}.extraction.yaml'
    if not record_file.is_file():
        produced = sorted(path.name.removesuffix('.extraction.yaml') for path in output.glob('*.extraction.yaml'))
        print(f'ERROR: the new run has no series {record["name"]} (found: {", ".join(produced) or "none"}); compare and add one of them by hand')
        return 1
    new_record = yaml.safe_load(record_file.read_text())
    new_record['supersedes'] = {'dataset': entry.meta.get('dataset'), 'sha256': entry.meta.get('sha256'), 'created_with': record.get('created', {}).get('tool')}
    for key in ('quantity', 'columns'):  # what the person entered stays (description, assignment, units, masses)
        if record.get(key):
            new_record[key] = record[key]
    record_file.write_text(yaml.safe_dump(new_record, sort_keys=False, allow_unicode=True, width=1000))
    new_table = read_raw((output / f'{record["name"]}.csv').read_text(encoding='utf-8'))
    comparison = compare_tables(read_raw(entry.path.read_text(encoding='utf-8')), new_table)
    print(f'Comparison with the stored extraction: {comparison}')
    problems = validate(new_record, new_table)
    if problems:
        # e.g. records from before 0.19.0 without target mass: the rules of this version apply to the new record
        print(f'Complete {record_file} first: ' + '; '.join(problems))
    print(f'Store the new version (review pending, it supersedes the old one): piclas-db literature add {record_file}')
    return 0


def run(args: argparse.Namespace) -> int:
    """Extract the data series of a vector figure, or a table, of a paper in the store into extraction records (pending review)"""
    if getattr(args, 'redo', None):
        return redo(args)
    if not args.paper or not args.page:
        print('ERROR: give PAPER and --page (or --redo PAPER/DATASET)')
        return 1
    if not args.list and not args.by:
        try:
            args.by = config.require_identity()  # who extracts: the configured user
        except config.ConfigError as e:
            print(f'ERROR: {e}')
            return 1
    store = Store(args.store)
    try:
        known = papers(store)
        paper_key = slug(args.paper)
        if paper_key not in known:
            raise LiteratureError(f'paper {paper_key} not in the store (piclas-db import <pdf> --literature {paper_key} --doi ...)')
        paper = known[paper_key]
        path = str(paper.path)
        if args.table:
            output = pathlib.Path(args.output)
            output.mkdir(parents=True, exist_ok=True)
            scan = args.ocr and args.columns and '=' not in args.columns  # a scan read cell by cell: also for the raw copy alone
            if (args.rates is not None or scan) and column_table(args, paper, path, output):
                return 0
            table = extract_table(path, page_list(args.page), args.table.split(',')[0], use_ocr=args.ocr)
            write_table(args, paper, table, output)
            return 0
        page = page_list(args.page)[0]
        scanned = args.raster or is_scanned(path, page)
        if args.list:
            if scanned:
                grid = pathlib.Path(args.output) / f'p{page}-grid.png'
                grid.parent.mkdir(parents=True, exist_ok=True)
                grid_image(path, page, str(grid))
                print(f'grid image (10 pt grid) for --frame-box, --x-points, --y-points and --seeds: {grid}')
            for index, frame in enumerate(raster_figure_frames(path, page) if scanned else figure_frames(path, page)):
                print(f'frame {index}: x {frame[0]:.1f}-{frame[2]:.1f} pt, y {frame[1]:.1f}-{frame[3]:.1f} pt (from the top of page {args.page})')
            return 0
        if scanned:
            box = numbers(args.frame_box)
            figure = extract_raster(
                path,
                page,
                args.frame,
                numbers(args.x_labels),
                numbers(args.y_labels),
                args.x_scale,
                args.y_scale,
                args.symbol_radius,
                (box[0], box[1], box[2], box[3]) if box else None,
                seed_points(args.seeds),
                pairs(args.x_points, '='),
                pairs(args.y_points, '='),
            )
        else:
            figure = extract(path, page, args.frame, numbers(args.x_labels), numbers(args.y_labels), args.x_scale, args.y_scale)
    except (ExtractError, LiteratureError, ValueError) as e:
        print(f'ERROR: {e}')
        return 1

    output = pathlib.Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    pdfplumber = require_pdfplumber()
    tools = {'pdfplumber': pdfplumber.__version__}
    if 'ocr' in (figure.x.source, figure.y.source):
        tools['tesseract'] = tesseract_version() or 'unknown'
    print(f'page {figure.page}, frame {args.frame}: {figure.tick_count[0]} x and {figure.tick_count[1]} y major ticks')
    for name, axis in (('x', figure.x), ('y', figure.y)):
        print(f'  {name} axis: {axis.scale}, labels {[value for _, value in axis.labels]} ({axis.source}), residual {axis.residual:.2g}')
    prefix = f'p{figure.page}-f{args.frame}'
    for series in figure.series:
        data = values(figure, series)
        name = slug(f'{args.name or prefix}-{series.name}')
        record = template(paper, name, str(figure.page), None, args.figure or f'page {args.page}, frame {args.frame}', 'raster' if scanned else 'vector')
        record['created']['by'] = args.by
        record['columns']['energy'] = {
            'unit': args.x_unit,
            'quantity': args.x_quantity,
            **({'frame': args.energy_frame} if args.energy_frame else {}),
            **({'mass_amu': args.mass_amu} if args.mass_amu else {}),
            **({'target_mass_amu': args.target_mass_amu} if args.target_mass_amu else {}),
        }
        record['columns']['cross_section']['unit'] = args.y_unit
        record['calibration'] = {
            axis_name: {'scale': axis.scale, 'labels_from': axis.source, 'labels': [[round(p, 4), v] for p, v in axis.labels], 'residual': axis.residual} for axis_name, axis in (('x', figure.x), ('y', figure.y))
        }
        record['parameters'] = {
            'page': figure.page,
            'frame': args.frame,
            'frame_pt': [round(v, 2) for v in figure.frame],
            'series': series.name,
            'kind': series.kind,
            'command': command_of(args),
        }
        if scanned:
            pixel = 1.0 / SCALE  # pt
            record['parameters'].update(
                {
                    'resolution_dpi': RESOLUTION,
                    'symbol_radius_px': args.symbol_radius,
                    **({'frame_box_pt': args.frame_box} if args.frame_box else {}),
                    **({'seeds': args.seeds} if args.seeds else {}),
                    **({'x_points': args.x_points} if args.x_points else {}),
                    **({'y_points': args.y_points} if args.y_points else {}),
                }
            )
            record['accuracy']['extraction'] = (
                f'symbol centre to about one pixel at {RESOLUTION} dpi: {abs(figure.x.b) * pixel:.2g} in x and {abs(figure.y.b) * pixel:.2g} in y '
                + ('(decades)' if figure.y.scale == 'log' else '(axis units)')
                + '; series assigned by continuity and majority of the symbol shapes'
            )
            flagged = [(index + 1, point.flag) for index, point in enumerate(series.points) if point.flag]
            if flagged:
                record['notes'] = [f'row {row}: ' + ('split from touching symbols' if flag == 'split' else 'recognized shape differs from the series') for row, flag in flagged]
            tools['scikit-image'] = importlib.metadata.version('scikit-image')
        else:
            record['accuracy']['extraction'] = 'coordinates as drawn in the PDF (vector graphics); limited by the calibration residual'
        record['environment'].update(tools)
        has_bars = bool(np.any(np.isfinite(data[:, 2])))
        record['result'] = {'points': len(data), 'error_bars': int(np.sum(np.isfinite(data[:, 2])))}
        lines = ['# extracted by piclas-db from vector graphics; values in axis units; uncertainty: half the error bar relative to the value', 'energy,cross_section' + (',uncertainty' if has_bars else '')]
        for x, y, low, high in data:
            row = f'{x:.10g},{y:.10g}'
            if has_bars:
                row += f',{abs(high - low) / 2 / abs(y):.6g}' if np.isfinite(low) and abs(y) > 0.0 else ','
            lines.append(row)
        (output / f'{name}.csv').write_text('\n'.join(lines) + '\n')
        (output / f'{name}.extraction.yaml').write_text(yaml.safe_dump(record, sort_keys=False, allow_unicode=True, width=1000))
        flags = sum(1 for point in series.points if point.flag)
        print(f'  {series.name:28s} {len(data):3d} points' + (f', {record["result"]["error_bars"]} error bars' if has_bars else '') + (f', {flags} flagged' if flags else '') + f' -> {output / name}.csv')
    review_image(path, figure, str(output / f'{prefix}-review.png'))
    print(f'Review image: {output / prefix}-review.png')
    print('Check the units and quantity in the records (velocity axis: --x-unit "a.u." --mass-amu ... --target-mass-amu ...), then:')
    print(f'  piclas-db literature add {output}/<series>.extraction.yaml')
    return 0
