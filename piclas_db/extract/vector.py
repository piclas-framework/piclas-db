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
"""Data from vector figures in PDF files ('piclas-db extract')

In a vector figure the markers, error bars, lines and ticks are drawing operations with exact coordinates, so the data can be read
instead of estimated from pixels:

1. frame: the innermost rectangle (or box of four lines) that contains markers or lines
2. ticks: short lines on the frame; the longest ones are the labelled major ticks
3. labels: text next to the major ticks (superscripts give powers of ten, e.g. 10^-20); figures whose labels are glyph outlines need
   OCR (Tesseract) or the labels given on the command line; linear or logarithmic scale from the labels
4. series: markers (rectangles and small closed paths) grouped by shape, fill and colour; lines (paths with many points)
5. error bars: vertical lines through the marker centres

The result is checked by the residual of the axis calibration and shown in a review image.
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import math
import operator
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Any, Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import numpy as np
# ==================================================================================================================================

MARKER_MAX = 12.0  # pt, larger closed shapes are not markers
TICK_MAX = 8.0  # pt
FRAME_MIN = 60.0  # pt


class ExtractError(Exception):
    """Figure cannot be extracted"""


def require_pdfplumber() -> Any:
    try:
        import pdfplumber  # noqa: PLC0415
    except ImportError as e:
        raise ExtractError('extracting figures needs pdfplumber: in your clone of piclas-db run python -m pip install -e ".[extract]"') from e
    return pdfplumber


Box = tuple[float, float, float, float]  # x0, top, x1, bottom in pt (top-down)


@dataclass
class Axis:
    scale: str  # 'linear' or 'log'
    a: float  # value (or log10 value) = a + b * coordinate
    b: float
    labels: list[tuple[float, float]]  # (tick coordinate, value) used
    residual: float  # largest deviation of a label from the fit (in value units, decades for log)
    source: str  # 'text', 'ocr' or 'given'

    def value(self, coordinate: float) -> float:
        result = self.a + self.b * coordinate
        return 10.0**result if self.scale == 'log' else result


@dataclass
class Point:
    x: float  # pt
    y: float  # pt
    low: Optional[float] = None  # error bar end (pt, larger y = lower value on screen)
    high: Optional[float] = None
    flag: Optional[str] = None  # scans: 'split' (from touching symbols), 'shape' (recognized shape differs from the series)


@dataclass
class Series:
    name: str  # e.g. 'square-open-0', 'circle-filled-0', 'line-1'
    kind: str  # 'marker' or 'line'
    points: list[Point] = field(default_factory=list)


@dataclass
class Figure:
    page: int  # 1-based
    frame: Box
    x: Axis
    y: Axis
    series: list[Series]
    tick_count: tuple[int, int]


# ----------------------------------------------------------------------------------------------------------------------------------
# Frame and ticks
# ----------------------------------------------------------------------------------------------------------------------------------
def inside(box: Box, x: float, y: float, margin: float = 0.5) -> bool:
    return box[0] - margin <= x <= box[2] + margin and box[1] - margin <= y <= box[3] + margin


def frames(page: Any) -> list[Box]:
    """Candidate plot frames: rectangles or boxes of four long lines, innermost first"""
    boxes = {(round(r['x0'], 1), round(r['top'], 1), round(r['x1'], 1), round(r['bottom'], 1)) for r in page.rects if r['width'] > FRAME_MIN and r['height'] > FRAME_MIN}
    horizontal = [line for line in page.lines if abs(line['bottom'] - line['top']) < 0.1 and line['x1'] - line['x0'] > FRAME_MIN]
    vertical = [line for line in page.lines if abs(line['x1'] - line['x0']) < 0.1 and line['bottom'] - line['top'] > FRAME_MIN]
    for left in vertical:
        for right in vertical:
            parallel = right['x0'] - left['x0'] > FRAME_MIN and abs(left['top'] - right['top']) < 0.5 and abs(left['bottom'] - right['bottom']) < 0.5
            closed = any(abs(h['top'] - left['top']) < 0.5 for h in horizontal) and any(abs(h['top'] - left['bottom']) < 0.5 for h in horizontal)
            if parallel and closed:
                boxes.add((round(left['x0'], 1), round(left['top'], 1), round(right['x0'], 1), round(left['bottom'], 1)))
    page_area = page.width * page.height
    boxes = {box for box in boxes if (box[2] - box[0]) * (box[3] - box[1]) < 0.8 * page_area}

    def contains(outer: Box, inner: Box) -> bool:
        return outer != inner and outer[0] <= inner[0] + 1 and outer[1] <= inner[1] + 1 and outer[2] >= inner[2] - 1 and outer[3] >= inner[3] - 1

    innermost = [box for box in boxes if not any(contains(box, other) for other in boxes)]
    return sorted(innermost, key=operator.itemgetter(1, 0))


def ticks(page: Any, frame: Box, axis: str) -> tuple[list[float], list[float]]:
    """Major and minor tick positions on the bottom (x) or left (y) edge of the frame"""
    found: dict[float, float] = {}
    for line in page.lines:
        width, height = line['x1'] - line['x0'], line['bottom'] - line['top']
        on_bottom = abs(line['bottom'] - frame[3]) < 0.6 or abs(line['top'] - frame[3]) < 0.6
        on_left = abs(line['x0'] - frame[0]) < 0.6 or abs(line['x1'] - frame[0]) < 0.6
        if axis == 'x' and width < 0.1 and 0.5 < height <= TICK_MAX and frame[0] - 0.5 <= line['x0'] <= frame[2] + 0.5 and on_bottom:
            found[round(line['x0'], 2)] = max(found.get(round(line['x0'], 2), 0.0), height)
        if axis == 'y' and height < 0.1 and 0.5 < width <= TICK_MAX and frame[1] - 0.5 <= line['top'] <= frame[3] + 0.5 and on_left:
            found[round(line['top'], 2)] = max(found.get(round(line['top'], 2), 0.0), width)
    if not found:
        return [], []
    longest = max(found.values())
    major = sorted(position for position, length in found.items() if length > 0.75 * longest)
    minor = sorted(position for position, length in found.items() if length <= 0.75 * longest)
    return major, minor


# ----------------------------------------------------------------------------------------------------------------------------------
# Labels
# ----------------------------------------------------------------------------------------------------------------------------------
def parse_label(main: str, superscript: str) -> Optional[float]:
    """'10' + '−20' -> 1e-20, '6×10' + '−21' -> 6e-21, '0.04' -> 0.04"""
    main = main.replace('−', '-').replace('–', '-').strip()
    superscript = superscript.replace('−', '-').replace('–', '-').strip()
    try:
        if superscript:
            mantissa, _, base = main.rpartition('×') if '×' in main else ('1', '', main)
            if base.strip() != '10':
                return None
            return float(mantissa or 1.0) * 10.0 ** int(superscript)
        return float(main)
    except ValueError:
        return None


def text_labels(page: Any, region: Box) -> list[tuple[float, float, float]]:
    """Numeric labels in a region: (x centre, y centre, value)"""
    chars = sorted((c for c in page.chars if inside(region, (c['x0'] + c['x1']) / 2, (c['top'] + c['bottom']) / 2, 0.0)), key=operator.itemgetter('x0'))
    groups: list[list[dict]] = []
    for char in chars:
        centre = (char['top'] + char['bottom']) / 2
        for group in groups:
            last = group[-1]
            size = max(c['size'] for c in group)
            if char['x0'] - last['x1'] < 0.6 * size and abs(centre - (last['top'] + last['bottom']) / 2) < 0.8 * size:
                group.append(char)
                break
        else:
            groups.append([char])
    labels = []
    for group in groups:
        size = max(c['size'] for c in group)
        main = ''.join(c['text'] for c in group if c['size'] >= 0.85 * size)
        superscript = ''.join(c['text'] for c in group if c['size'] < 0.85 * size)
        value = parse_label(main, superscript)
        if value is not None:
            big = [c for c in group if c['size'] >= 0.85 * size]
            labels.append(((min(c['x0'] for c in group) + max(c['x1'] for c in group)) / 2, (min(c['top'] for c in big) + max(c['bottom'] for c in big)) / 2, value))
    return labels


def ocr_labels(page: Any, region: Box) -> list[tuple[float, float, float]]:
    """Labels drawn as glyph outlines: OCR (Tesseract) on a 600 dpi rendering of the region"""
    if shutil.which('tesseract') is None:
        return []
    scale = 600 / 72
    region = (max(region[0], 0.0), max(region[1], 0.0), min(region[2], float(page.width)), min(region[3], float(page.height)))
    image = page.crop(region).to_image(resolution=600).original
    labels: list[tuple[float, float, float]] = []
    with tempfile.NamedTemporaryFile(suffix='.png') as file:
        image.save(file.name)
        # sparse text and single block, restricted to the characters of numbers; both results are combined
        for mode in ('11', '6'):
            tsv = subprocess.run(['tesseract', file.name, '-', '--psm', mode, '-c', 'tessedit_char_whitelist=0123456789.-', 'tsv'], capture_output=True, text=True, check=False).stdout
            for line in tsv.splitlines()[1:]:
                fields = line.split('\t')
                if len(fields) == 12 and re.fullmatch(r'-?\d+(\.\d+)?', fields[11].strip()):
                    x = region[0] + (int(fields[6]) + int(fields[8]) / 2) / scale
                    y = region[1] + (int(fields[7]) + int(fields[9]) / 2) / scale
                    if not any(abs(x - other[0]) < 3 and abs(y - other[1]) < 3 for other in labels):
                        labels.append((x, y, float(fields[11])))
    return labels


def tesseract_version() -> Optional[str]:
    if shutil.which('tesseract') is None:
        return None
    output = subprocess.run(['tesseract', '--version'], capture_output=True, text=True, check=False)
    return (output.stdout or output.stderr).splitlines()[0].strip() if (output.stdout or output.stderr) else None


def calibrate(major: list[float], labels: list[tuple[float, float]], source: str, scale: Optional[str]) -> Axis:
    """Fit value = a + b * coordinate (or log10(value)) through labelled ticks; every pair of labels proposes a fit, the fit
    with most labels agreeing wins (OCR errors are rejected)"""
    if len(labels) < 2:
        hint = ' (Tesseract is not installed: the labels of this figure are outlines and need OCR, or give them)' if source == 'none' and shutil.which('tesseract') is None else ''
        raise ExtractError(f'fewer than two tick labels found ({source}){hint}; give them with --x-labels / --y-labels (major ticks, x left to right, y bottom to top)')
    positions = np.array([position for position, _ in labels])
    values = np.array([value for _, value in labels])
    if scale is None:
        scale = 'linear'
        if np.all(values > 0.0) and len(values) > 2:
            # logarithmic if the values fit a line in log10 much better than linearly
            linear_fit = np.polyfit(positions, values, 1)
            log_fit = np.polyfit(positions, np.log10(values), 1)
            linear_error = np.max(np.abs(np.polyval(linear_fit, positions) - values)) / np.ptp(values)
            log_error = np.max(np.abs(np.polyval(log_fit, positions) - np.log10(values))) / max(np.ptp(np.log10(values)), 1e-30)
            scale = 'log' if log_error < 0.2 * linear_error else 'linear'
    target = np.log10(values) if scale == 'log' else values
    best: Optional[np.ndarray] = None
    # tolerance from the typical step between labels (not from the range, which a misread label such as 20 for 2.0 inflates)
    steps = np.diff(np.unique(np.round(target, 12)))
    tolerance = 0.2 * float(np.median(steps)) if len(steps) else 1e-30
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            if abs(positions[j] - positions[i]) < 1e-6:
                continue
            b = (target[j] - target[i]) / (positions[j] - positions[i])
            inliers = np.abs(target[i] + b * (positions - positions[i]) - target) < tolerance
            if best is None or inliers.sum() > best.sum():
                best = inliers
    if best is None or best.sum() < 2:
        raise ExtractError(f'tick labels ({source}) do not fit a {scale} axis')
    b, a = np.polyfit(positions[best], target[best], 1)
    residual = float(np.max(np.abs(a + b * positions[best] - target[best])))
    used = [(float(p), float(v)) for p, v, ok in zip(positions, values, best, strict=True) if ok]
    return Axis(scale=scale, a=float(a), b=float(b), labels=used, residual=residual, source=source)


def axis_labels(page: Any, frame: Box, axis: str, major: list[float], minor: list[float], given: Optional[list[float]]) -> tuple[list[tuple[float, float]], str]:
    """(tick position, value) pairs: given on the command line, from the text, or by OCR"""
    if given:
        if len(given) != len(major):
            raise ExtractError(f'{len(given)} {axis} labels given for {len(major)} major ticks')
        order = major if axis == 'x' else major[::-1]  # labels are given from the origin: left to right, bottom to top
        return list(zip(order, given, strict=True)), 'given'
    region = (frame[0] - 20, frame[3] + 0.5, frame[2] + 20, frame[3] + 30) if axis == 'x' else (frame[0] - 60, frame[1] - 8, frame[0] - 0.5, frame[3] + 8)
    for source, labels in (('text', text_labels(page, region)), ('ocr', None)):
        if labels is None:
            labels = ocr_labels(page, region)
        pairs = []
        for x, y, value in labels:
            coordinate = x if axis == 'x' else y
            candidates = major + minor  # labelled minor ticks count too (e.g. 2x10^-20 on short logarithmic axes)
            tick = min(candidates, key=lambda t: abs(t - coordinate)) if candidates else None
            if tick is not None and abs(tick - coordinate) < 6.0:
                pairs.append((tick, value))
        if len({tick for tick, _ in pairs}) >= 2:
            return sorted(set(pairs)), source
    return [], 'none'


# ----------------------------------------------------------------------------------------------------------------------------------
# Series
# ----------------------------------------------------------------------------------------------------------------------------------
COLOUR_NAMES = {'000000': 'black', 'ffffff': 'white', 'ff0000': 'red', '00ff00': 'green', '0000ff': 'blue'}


def colour(value: Any) -> str:
    """Readable colour name for series names: grey values and RGB as hex, common colours by name"""
    if value is None:
        return 'none'
    components = (value,) if isinstance(value, (int, float)) else tuple(value)
    if len(components) == 1:
        components = components * 3  # grey
    code = ''.join(f'{round(float(component) * 255):02x}' for component in components[:3])
    return COLOUR_NAMES.get(code, code)


def shape_of(obj: dict) -> str:
    if obj['object_type'] == 'rect':
        return 'square'
    points = obj.get('pts') or []
    if len(points) <= 5:
        return 'triangle' if len(points) in (3, 4) else f'path{len(points)}'
    return 'circle'


def series_of(page: Any, frame: Box) -> list[Series]:
    """Markers grouped by shape, fill and colour; lines as separate series"""
    markers: dict[str, list[Point]] = {}
    seen: set[tuple[float, float, str]] = set()
    lines: list[Series] = []
    for obj in [*page.rects, *page.curves]:
        width, height = obj['x1'] - obj['x0'], obj['bottom'] - obj['top']
        x, y = (obj['x0'] + obj['x1']) / 2, (obj['top'] + obj['bottom']) / 2
        if not inside(frame, x, y):
            continue
        if width <= MARKER_MAX and height <= MARKER_MAX and width > 0.5 and height > 0.5:
            shape = shape_of(obj)
            filled = obj.get('fill') and colour(obj.get('non_stroking_color')) != 'white'
            name = f'{shape}-{"filled" if filled else "open"}-{colour(obj.get("non_stroking_color") if filled else obj.get("stroking_color"))}'
            key = (round(x, 1), round(y, 1), shape)
            if filled:
                # a filled marker is often drawn twice (fill and outline): one point, filled
                markers.setdefault(name, [])
                if key in seen:
                    for points in markers.values():
                        points[:] = [p for p in points if (round(p.x, 1), round(p.y, 1)) != key[:2]]
                markers[name].append(Point(x, y))
                seen.add(key)
            elif key not in seen:
                markers.setdefault(name, []).append(Point(x, y))
                seen.add(key)
        elif obj['object_type'] == 'curve' and len(obj.get('pts') or []) >= 6 and width > 0.1 * (frame[2] - frame[0]):
            points = [Point(px, py) for px, py in obj['pts'] if inside(frame, px, py)]
            if points:
                lines.append(Series(f'line-{len(lines) + 1}-{colour(obj.get("stroking_color"))}', 'line', points))
    series = [Series(name, 'marker', sorted(points, key=lambda p: p.x)) for name, points in sorted(markers.items()) if points]
    for item in series:
        for point in item.points:
            bars = [
                line
                for line in page.lines
                if abs(line['x1'] - line['x0']) < 0.1 and abs(line['x0'] - point.x) < 0.3 and line['top'] <= point.y + 3.0 and line['bottom'] >= point.y - 3.0 and line['bottom'] - line['top'] > 0.3
            ]
            if bars:
                point.high, point.low = min(line['top'] for line in bars), max(line['bottom'] for line in bars)
    return series + lines


# ----------------------------------------------------------------------------------------------------------------------------------
# Figure
# ----------------------------------------------------------------------------------------------------------------------------------
def extract(
    path: str,
    page_number: int,
    frame_index: int = 0,
    x_labels: Optional[list[float]] = None,
    y_labels: Optional[list[float]] = None,
    x_scale: Optional[str] = None,
    y_scale: Optional[str] = None,
) -> Figure:
    pdfplumber = require_pdfplumber()
    with pdfplumber.open(path) as pdf:
        if not 1 <= page_number <= len(pdf.pages):
            raise ExtractError(f'page {page_number} does not exist ({len(pdf.pages)} pages)')
        page = pdf.pages[page_number - 1]
        if page.images and not page.curves and not page.rects:
            raise ExtractError(f'page {page_number} is a scanned image: vector extraction is not possible')
        candidates = [box for box in frames(page) if series_of(page, box)]
        if not candidates:
            raise ExtractError(f'no plot frame with markers or lines on page {page_number}')
        if frame_index >= len(candidates):
            raise ExtractError(f'frame {frame_index} does not exist ({len(candidates)} frames with data on page {page_number})')
        frame = candidates[frame_index]
        x_major, x_minor = ticks(page, frame, 'x')
        y_major, y_minor = ticks(page, frame, 'y')
        x_pairs, x_source = axis_labels(page, frame, 'x', x_major, x_minor, x_labels)
        y_pairs, y_source = axis_labels(page, frame, 'y', y_major, y_minor, y_labels)
        x_axis = calibrate(x_major, x_pairs, x_source, x_scale)
        y_axis = calibrate(y_major, y_pairs, y_source, y_scale)
        return Figure(page_number, frame, x_axis, y_axis, series_of(page, frame), (len(x_major), len(y_major)))


def figure_frames(path: str, page_number: int) -> list[Box]:
    pdfplumber = require_pdfplumber()
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[page_number - 1]
        return [box for box in frames(page) if series_of(page, box)]


def values(figure: Figure, series: Series) -> np.ndarray:
    """(n_rows, 4): x, y, y_low, y_high in axis units (NaN without error bar)"""
    rows = []
    for point in series.points:
        low = figure.y.value(point.low) if point.low is not None else math.nan
        high = figure.y.value(point.high) if point.high is not None else math.nan
        rows.append((figure.x.value(point.x), figure.y.value(point.y), low, high))
    return np.array(rows, dtype=np.float64).reshape(-1, 4)


def review_image(path: str, figure: Figure, output: str) -> None:
    """Rendering of the figure with the extracted points (circles), flagged points (orange squares), error bars (blue) and
    calibration ticks (magenta)"""
    pdfplumber = require_pdfplumber()
    from PIL import ImageDraw  # noqa: PLC0415

    palette = [(220, 0, 0), (0, 150, 0), (0, 0, 230), (230, 120, 0), (150, 0, 150), (0, 150, 150)]
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[figure.page - 1]
        margin = 45.0
        box = (max(figure.frame[0] - margin, 0), max(figure.frame[1] - 15, 0), min(figure.frame[2] + 15, page.width), min(figure.frame[3] + 35, page.height))
        resolution = 200
        scale = resolution / 72
        image = page.crop(box).to_image(resolution=resolution).original.convert('RGB')
    draw = ImageDraw.Draw(image)

    def pixel(x: float, y: float) -> tuple[float, float]:
        return (x - box[0]) * scale, (y - box[1]) * scale

    for index, series in enumerate(figure.series):
        tone = palette[index % len(palette)]
        for point in series.points:
            px, py = pixel(point.x, point.y)
            draw.ellipse([px - 7, py - 7, px + 7, py + 7], outline=tone, width=2)
            if point.flag:
                draw.rectangle([px - 11, py - 11, px + 11, py + 11], outline=(255, 140, 0), width=2)
            if point.low is not None and point.high is not None:
                for end in (point.low, point.high):
                    _, ey = pixel(point.x, end)
                    draw.line([(px - 9, ey), (px + 9, ey)], fill=(0, 0, 255), width=2)
    for position, _ in figure.x.labels:
        px, py = pixel(position, figure.frame[3])
        draw.line([(px, py), (px, py + 12)], fill=(255, 0, 255), width=2)
    for position, _ in figure.y.labels:
        px, py = pixel(figure.frame[0], position)
        draw.line([(px - 12, py), (px, py)], fill=(255, 0, 255), width=2)
    image.save(output)
