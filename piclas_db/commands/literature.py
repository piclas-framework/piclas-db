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

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import yaml

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.git import GitError
from piclas_db.literature import LiteratureError, add_extraction, extractions, find_extraction, papers, review, template
from piclas_db.sources.identify import slug
from piclas_db.store import Store
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
            record = template(known[paper_name], name, args.page, args.table, args.figure, args.method, args.equation, args.formula)
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
            else:
                data_file.write_text(CSV_TEMPLATE)
            record_file.write_text(yaml.safe_dump(record, sort_keys=False, allow_unicode=True, width=1000))
            print(f'Enter the values in {data_file}, complete {record_file} (units, created.by, quantity, accuracy), then:')
            print(f'  piclas-db literature add {record_file}')
        elif args.action == 'add':
            if len(args.arguments) != 1:
                raise LiteratureError('usage: piclas-db literature add RECORD.yaml')
            entry = add_extraction(store, pathlib.Path(args.arguments[0]))
            print(f'stored  literature/{entry.meta["dataset"]}@{str(entry.meta["sha256"])[:8]} ({entry.meta["extraction"]["result"]["rows"]} rows, review pending)')
            print(f'Review it against the paper: piclas-db literature review {entry.meta["dataset"]} --approve --reviewer "<name>"')
        elif args.action == 'review':
            if len(args.arguments) != 1 or args.approve == args.reject or not args.reviewer:
                raise LiteratureError('usage: piclas-db literature review PAPER/NAME[@SHA] (--approve | --reject) --reviewer NAME [--notes TEXT]')
            entry = find_extraction(store, args.arguments[0])
            status = 'approved' if args.approve else 'rejected'
            review(store, entry, status, args.reviewer, args.notes)
            print(f'{entry.meta["dataset"]}: {status} by {args.reviewer}')
        else:
            for name, paper in sorted(papers(store).items()):
                print(f'{name:24s} {paper.meta.get("doi") or ""}  {paper.meta.get("reference") or ""}')
                for entry in extractions(store):
                    if str(entry.meta.get('dataset', '')).startswith(name + '/'):
                        record = entry.meta.get('extraction') or {}
                        source = record.get('source') or {}
                        where = ', '.join(f'{label} {source[label]}' for label in ('table', 'figure', 'page') if source.get(label))
                        status = (record.get('review') or {}).get('status')
                        print(f'  {entry.meta["dataset"]}@{str(entry.meta["sha256"])[:8]}  {record.get("method")}, {where}, review {status}')
    except (LiteratureError, GitError) as e:
        print(f'ERROR: {e}')
        return 1
    return 0
