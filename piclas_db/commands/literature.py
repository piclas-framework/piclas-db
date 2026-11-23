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
import pathlib
from typing import Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import yaml

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db import config, wanted
from piclas_db.git import GitError
from piclas_db.literature import LiteratureError, add_extraction, check_extraction, extractions, find_extraction, papers, review, template
from piclas_db.sources.identify import slug
from piclas_db.store import Store, StoreEntry
# ==================================================================================================================================

CSV_TEMPLATE = """# Values exactly as printed in the paper, in the units given in the extraction record (columns: energy, cross_section[, uncertainty])
# Lines starting with # are comments. Delete these comment lines or keep them, as you like.
energy,cross_section
"""


FORMULA_TEMPLATE = """# Fit formula exactly as printed in the paper; E is the energy in the unit of the record (columns.energy.unit)
# Allowed: + - * / ** (or ^), exp, log, log10, sqrt, abs, numbers, E and the parameters below
expression: a / E**b
parameters: {a: 1.0, b: 0.5}
threshold: null   # energy below which the cross-section is zero (e.g. where the formula is not defined)
range: [1.0, 1000.0]   # validity range given in the paper
points: 200   # logarithmic grid over the range
"""


RATES_TEMPLATE = """# Reaction rate table exactly as printed: one row per reaction and third body; C in the unit of the record (columns.rate.unit)
# reaction: species as printed (N2+, NO+, e-), third bodies as M or A; third_body: species of the row, a list "N2, O2", others or all
# C: 3.0e22 or as printed 3.0^22; Tx: T, Ta (sqrt(T Tv)), Tv, Te
row,reaction,third_body,C,n,Td,Tx
"""


def kind_of(record: dict) -> str:
    """What an extraction holds, in words"""
    if record.get('raw_table'):
        return 'raw copy'
    if record.get('rate_table'):
        mixture = (record.get('quantity') or {}).get('mixture')
        model = ((record.get('quantity') or {}).get('assignment') or {}).get('chemistry_model')
        return 'rate table' + (f' ({mixture})' if mixture else '') + (f', {model}' if model else '')
    if record.get('parameter_table'):
        return 'parameter table'
    if record.get('formula'):
        return 'fit formula'
    return 'data series'


def extraction_line(entry: StoreEntry) -> str:
    """One line of literature list: name, page (PDF page, printed page in brackets as recorded), table or figure, kind, rows, method,
    review status"""
    record = entry.meta.get('extraction') or {}
    source = record.get('source') or {}
    name = str(entry.meta.get('dataset', '')).partition('/')[2] + f'@{str(entry.meta.get("sha256"))[:8]}'
    where = ', '.join(f'{label} {source[label]}' for label in ('table', 'figure') if source.get(label))
    rows = (record.get('result') or {}).get('rows')
    status = (record.get('review') or {}).get('status')
    return f'{name:32s} p. {source.get("page") or "?"!s:14s} {where:12s} {kind_of(record)}' + (f', {rows} rows' if rows is not None else '') + f', {record.get("method")}, review {status}'


def check_only(store: Store, record_path: pathlib.Path, compare: Optional[str]) -> int:
    """literature add -n: validate the record, show what would be stored; rate tables row by row, optionally compared with a database"""
    from piclas_db import rates  # noqa: PLC0415
    from piclas_db.common.table import Row, render, use_color  # noqa: PLC0415

    record, data_path, table = check_extraction(store, record_path)
    paper, name = record['source']['paper'], record['name']
    if not record.get('rate_table'):
        rows = len(table.energy) if not record.get('parameter_table') else record.get('result', {}).get('rows')
        print(f'valid: literature/{paper}/{name} ({rows} rows) would be stored (dry run, nothing stored)')
        return 0
    unit = str(((record.get('columns') or {}).get('rate') or {}).get('unit'))
    model = ((record.get('quantity') or {}).get('assignment') or {}).get('chemistry_model')
    rate_rows = rates.read_rate_table(data_path.read_text(encoding='utf-8'))
    database = None
    if compare:
        from piclas_db.readers import read_database  # noqa: PLC0415

        database = read_database(compare)
    header, lines, counts = rates.preview(rate_rows, unit, database)
    print(
        f'valid: literature/{paper}/{name} (p. {(record.get("source") or {}).get("page")}, table {(record.get("source") or {}).get("table")}): {len(rate_rows)} rows, {len({str(row.key) for row in rate_rows})} reactions, C in {unit} -> m^3/s per molecule, chemistry model {model or "(none)"} (dry run, nothing stored)'
    )
    color = use_color()
    print('\n'.join(render(header, [Row(line) for line in lines], shrinkable=[1, len(header) - 1] if database else [1], color=color)))
    if database is not None:
        print(f'{compare}: {counts["same"]} row(s) with the same values, {counts["differs"]} with other values (≠), {counts["absent"]} reaction(s) not in the database')
    print(f'Store it with: piclas-db literature add {record_path}')
    return 0


def run(args: argparse.Namespace) -> int:
    """Data from papers: create entry templates, store extractions with their record, review them, list them"""
    store = Store(args.store)
    try:
        if args.action == 'template':
            if len(args.arguments) != 2:
                raise LiteratureError('usage: piclas-db literature template PAPER NAME [--page P --table T | --figure F]')
            paper_name, name = slug(args.arguments[0]), slug(args.arguments[1])
            known = papers(store)
            if paper_name not in known:
                raise LiteratureError(f'paper {paper_name} not in the store (piclas-db import <pdf> --literature {paper_name} --doi ...)')
            directory = pathlib.Path(args.output)
            directory.mkdir(parents=True, exist_ok=True)
            record_file, data_file = directory / f'{name}.extraction.yaml', directory / f'{name}.csv'
            if record_file.exists() or data_file.exists():
                raise LiteratureError(f'{record_file} or {data_file} exists already')
            record = template(known[paper_name], name, args.page, args.table, args.figure, args.method, args.equation, args.formula, rates=args.rates)
            if args.formula:
                data_file = directory / f'{name}.formula.yaml'
                if data_file.exists():
                    raise LiteratureError(f'{data_file} exists already')
                text = FORMULA_TEMPLATE
                if args.parameters_from:
                    column = int(args.column) if str(args.column or '').isdigit() else args.column
                    text = text.replace(
                        'parameters: {a: 1.0, b: 0.5}\n',
                        'parameters: {}   # further constants\n'
                        + yaml.safe_dump({'parameters_from': {'table': args.parameters_from, 'column': column or 1, 'rows': {}}}, sort_keys=False, allow_unicode=True)
                        + '# rows: parameter name -> row label of the table, only where they differ (labels compared without spaces)\n',
                    )
                data_file.write_text(text)
            elif args.rates:
                data_file.write_text(RATES_TEMPLATE)
            else:
                data_file.write_text(CSV_TEMPLATE)
            record_file.write_text(yaml.safe_dump(record, sort_keys=False, allow_unicode=True, width=1000))
            print(f'Enter the values in {data_file}, complete {record_file} (units, created.by, quantity, accuracy), then:')
            print(f'  piclas-db literature add {record_file}')
        elif args.action == 'add' and args.dry_run:
            if len(args.arguments) != 1:
                raise LiteratureError('usage: piclas-db literature add -n RECORD.yaml [--compare DATABASE.h5]')
            return check_only(store, pathlib.Path(args.arguments[0]), args.compare)
        elif args.action == 'add':
            if len(args.arguments) != 1:
                raise LiteratureError('usage: piclas-db literature add RECORD.yaml')
            entry = add_extraction(store, pathlib.Path(args.arguments[0]), by=config.require_identity())
            print(f'stored  literature/{entry.meta["dataset"]}@{str(entry.meta["sha256"])[:8]} ({entry.meta["extraction"]["result"]["rows"]} rows, review pending)')
            print(f'Review it against the paper: piclas-db literature review {entry.meta["dataset"]} --approve')
        elif args.action == 'review':
            if len(args.arguments) != 1 or args.approve == args.reject:
                raise LiteratureError('usage: piclas-db literature review PAPER/NAME[@SHA] (--approve | --reject) [--reviewer NAME] [--notes TEXT]')
            args.reviewer = args.reviewer or config.require_identity()  # default: the configured user
            entry = find_extraction(store, args.arguments[0])
            status = 'approved' if args.approve else 'rejected'
            review(store, entry, status, args.reviewer, args.notes)
            print(f'{entry.meta["dataset"]}: {status} by {args.reviewer}')
        elif args.action == 'want':
            if len(args.arguments) != 1 or not args.reference:
                raise LiteratureError('usage: piclas-db literature want KEY --reference TEXT [--doi DOI] [--needed-for TEXT] [--note TEXT]')
            if args.arguments[0] in papers(store):
                raise LiteratureError(f'{args.arguments[0]} is already in the store')
            name = wanted.add(store, args.arguments[0], args.reference, args.needed_for, args.doi, args.note, by=config.require_identity())
            print(f'{name}: on the wanted list ({len(wanted.load(store))} paper(s) wanted)')
        elif args.action == 'unwant':
            if len(args.arguments) != 1:
                raise LiteratureError('usage: piclas-db literature unwant KEY')
            wanted.drop(store, args.arguments[0])
            print(f'{args.arguments[0]}: removed from the wanted list')
        elif args.action == 'wanted':
            entries = wanted.load(store)
            print('\n'.join(wanted.describe(entries)) if entries else 'No papers wanted')
        else:
            for name, paper in sorted(papers(store).items()):
                print(f'{name:24s} {paper.meta.get("doi") or ""}  {paper.meta.get("reference") or ""}')
                for entry in sorted(extractions(store), key=lambda e: str(e.meta.get('dataset'))):
                    if str(entry.meta.get('dataset', '')).startswith(name + '/'):
                        print('  ' + extraction_line(entry))
    except (LiteratureError, GitError, config.ConfigError, wanted.WantedError) as e:
        print(f'ERROR: {e}')
        return 1
    return 0
