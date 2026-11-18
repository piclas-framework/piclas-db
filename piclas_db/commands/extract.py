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
import numpy as np
import yaml

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.extract.vector import ExtractError, extract, figure_frames, require_pdfplumber, review_image, tesseract_version, values
from piclas_db.literature import LiteratureError, papers, template
from piclas_db.sources.identify import slug
from piclas_db.store import Store
# ==================================================================================================================================


def numbers(text: Optional[str]) -> Optional[list[float]]:
    return [float(part) for part in text.split(',')] if text else None


def run(args: argparse.Namespace) -> int:
    """Extract the data series of a vector figure of a paper in the store into extraction records (pending review)"""
    store = Store(args.store)
    try:
        known = papers(store)
        paper_key = slug(args.paper)
        if paper_key not in known:
            raise LiteratureError(f'paper {paper_key} not in the store (piclas-db import <pdf> --literature {paper_key} --doi ...)')
        paper = known[paper_key]
        path = str(paper.path)
        if args.list:
            for index, frame in enumerate(figure_frames(path, args.page)):
                print(f'frame {index}: x {frame[0]:.1f}-{frame[2]:.1f} pt, y {frame[1]:.1f}-{frame[3]:.1f} pt (from the top of page {args.page})')
            return 0
        figure = extract(path, args.page, args.frame, numbers(args.x_labels), numbers(args.y_labels), args.x_scale, args.y_scale)
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
        record = template(paper, name, str(args.page), None, args.figure or f'page {args.page}, frame {args.frame}', 'vector')
        record['created']['by'] = args.by
        record['columns']['energy'] = {'unit': args.x_unit, 'quantity': args.x_quantity, **({'mass_amu': args.mass_amu} if args.mass_amu else {})}
        record['columns']['cross_section']['unit'] = args.y_unit
        record['calibration'] = {
            axis_name: {'scale': axis.scale, 'labels_from': axis.source, 'labels': [[round(p, 4), v] for p, v in axis.labels], 'residual': axis.residual} for axis_name, axis in (('x', figure.x), ('y', figure.y))
        }
        record['parameters'] = {'page': args.page, 'frame': args.frame, 'frame_pt': [round(v, 2) for v in figure.frame], 'series': series.name, 'kind': series.kind}
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
        print(f'  {series.name:28s} {len(data):3d} points' + (f', {record["result"]["error_bars"]} error bars' if has_bars else '') + f' -> {output / name}.csv')
    review_image(path, figure, str(output / f'{prefix}-review.png'))
    print(f'Review image: {output / prefix}-review.png')
    print('Check the units and quantity in the records (energy axis may be a velocity: --x-unit "a.u." --mass-amu ...), then:')
    print(f'  piclas-db literature add {output}/<series>.extraction.yaml')
    return 0
