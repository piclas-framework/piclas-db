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
import pathlib
from typing import Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import numpy as np
import yaml

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.extract.raster import RESOLUTION, SCALE, extract_raster, is_scanned, raster_figure_frames
from piclas_db.extract.table import Table, extract_table, header_unit, parse_number
from piclas_db.extract.vector import ExtractError, extract, figure_frames, require_pdfplumber, review_image, tesseract_version, values
from piclas_db.literature import LiteratureError, papers, template
from piclas_db.sources.identify import slug
from piclas_db.store import Store, StoreEntry
# ==================================================================================================================================


def numbers(text: Optional[str]) -> Optional[list[float]]:
    return [float(part) for part in text.split(',')] if text else None


def page_list(text: str) -> list[int]:
    """'14', '14-15' or '4,5'"""
    pages: list[int] = []
    for part in text.split(','):
        first, _, last = part.partition('-')
        pages += list(range(int(first), int(last or first) + 1))
    return pages


def write_table(args: argparse.Namespace, paper: StoreEntry, table: Table, output: pathlib.Path) -> None:
    """Raw table as CSV; for tables with an energy column one series per further column (CSV as printed + extraction record)"""
    import csv  # noqa: PLC0415

    name = slug(args.name or f'table{table.number}')
    with (output / f'{name}-table.csv').open('w', newline='') as file:
        writer = csv.writer(file, lineterminator='\n')
        writer.writerow(table.header)
        writer.writerows(table.rows)
    print(f'table {table.number} (pages {", ".join(str(p) for p in table.pages)}, {table.source}): {len(table.rows)} rows, {len(table.header)} columns -> {output / name}-table.csv')
    print(f'  caption: {table.caption}')
    parsed = [parse_number(row[0]) for row in table.rows]
    energies = [value for value in parsed if value is not None]
    if len(energies) != len(parsed) or any(b <= a for a, b in itertools.pairwise(energies)):
        print('  no increasing energy column: kept as raw table (e.g. fit parameters)')
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
        record['parameters'] = {'pages': table.pages, 'table': table.number, 'column': column, 'header': table.header[column]}
        record['result'] = {'rows': len(rows)}
        lines = [f'# table {table.number}, column {column}: {table.header[column]}', 'energy,cross_section'] + [f'{parse_number(e)!r},{parse_number(v)!r}' for e, v in rows]
        (output / f'{series}.csv').write_text('\n'.join(lines) + '\n')
        (output / f'{series}.extraction.yaml').write_text(yaml.safe_dump(record, sort_keys=False, allow_unicode=True, width=1000))
        units = f'{record["columns"]["energy"]["unit"]}, {record["columns"]["cross_section"]["unit"]}'
        print(f'  column {column}: {len(rows)} values ({units}) -> {output / series}.csv')
    print(f'Check the records against the paper, then: piclas-db literature add {output}/<series>.extraction.yaml')


def run(args: argparse.Namespace) -> int:
    """Extract the data series of a vector figure, or a table, of a paper in the store into extraction records (pending review)"""
    store = Store(args.store)
    try:
        known = papers(store)
        paper_key = slug(args.paper)
        if paper_key not in known:
            raise LiteratureError(f'paper {paper_key} not in the store (piclas-db import <pdf> --literature {paper_key} --doi ...)')
        paper = known[paper_key]
        path = str(paper.path)
        if args.table:
            table = extract_table(path, page_list(args.page), args.table, use_ocr=args.ocr)
            output = pathlib.Path(args.output)
            output.mkdir(parents=True, exist_ok=True)
            write_table(args, paper, table, output)
            return 0
        page = page_list(args.page)[0]
        scanned = args.raster or is_scanned(path, page)
        if args.list:
            for index, frame in enumerate(raster_figure_frames(path, page) if scanned else figure_frames(path, page)):
                print(f'frame {index}: x {frame[0]:.1f}-{frame[2]:.1f} pt, y {frame[1]:.1f}-{frame[3]:.1f} pt (from the top of page {args.page})')
            return 0
        if scanned:
            figure = extract_raster(path, page, args.frame, numbers(args.x_labels), numbers(args.y_labels), args.x_scale, args.y_scale, args.symbol_radius)
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
        record['parameters'] = {'page': figure.page, 'frame': args.frame, 'frame_pt': [round(v, 2) for v in figure.frame], 'series': series.name, 'kind': series.kind}
        if scanned:
            pixel = 1.0 / SCALE  # pt
            record['parameters'].update({'resolution_dpi': RESOLUTION, 'symbol_radius_px': args.symbol_radius})
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
    print('Check the units and quantity in the records (energy axis may be a velocity: --x-unit "a.u." --mass-amu ...), then:')
    print(f'  piclas-db literature add {output}/<series>.extraction.yaml')
    return 0
