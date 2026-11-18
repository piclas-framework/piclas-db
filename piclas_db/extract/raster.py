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
"""Data from scanned figures ('piclas-db extract' on pages without vector graphics)

The page is rendered at 300 dpi and binarized. The plot frame is the innermost box of long horizontal and vertical lines (or the
two axes); ticks are short lines on the bottom and left edge; their labels are read by OCR (Tesseract) or given on the command line.
Filled symbols remain after a morphological opening that removes lines and text strokes; symbols that touch are split along their
direction. Points are linked into series from left to right by continuity, and each series is named by the majority of the
recognized shapes (square, circle, triangle): the shape of single symbols is not reliable at this resolution. Points from split
symbols and points whose shape differs from their series are flagged for the review.

Accuracy: about one pixel (0.085 pt at 300 dpi) for the symbol centre, given in axis units in the extraction record.
"""

# ----------------------------------------------------------------------------------------------------------------------------------
# Standard libraries
# ----------------------------------------------------------------------------------------------------------------------------------
from typing import Any, Optional

# ----------------------------------------------------------------------------------------------------------------------------------
# Third-party libraries
# ----------------------------------------------------------------------------------------------------------------------------------
import numpy as np

# ----------------------------------------------------------------------------------------------------------------------------------
# Local imports
# ----------------------------------------------------------------------------------------------------------------------------------
from piclas_db.extract.vector import Box, ExtractError, Figure, Point, Series, calibrate, ocr_labels, require_pdfplumber
# ==================================================================================================================================

RESOLUTION = 300  # dpi
SCALE = RESOLUTION / 72  # pixels per pt


def require_skimage() -> Any:
    try:
        from skimage import measure, morphology  # noqa: PLC0415
    except ImportError as e:
        raise ExtractError('extracting scanned figures needs scikit-image: pip install "piclas-db[extract]"') from e
    return measure, morphology


def runs(row: np.ndarray, minimum: int) -> list[tuple[int, int]]:
    """Start and end (exclusive) of runs of ink of at least 'minimum' pixels"""
    padded = np.concatenate([[False], row, [False]])
    changes = np.flatnonzero(np.diff(padded.astype(np.int8)))
    return [(int(a), int(b)) for a, b in zip(changes[::2], changes[1::2], strict=True) if b - a >= minimum]


def long_lines(ink: np.ndarray, minimum: int) -> list[tuple[int, int, int]]:
    """Horizontal lines (row, start, end) of at least 'minimum' pixels; pieces in neighbouring rows (thick or slightly skewed
    lines of a scan) are joined into one line"""
    pieces = [(index, start, end) for index in range(ink.shape[0]) for start, end in runs(ink[index], minimum // 3)]
    lines: list[list[int]] = []  # row, start, end, last row
    for row, start, end in pieces:
        for line in lines:
            if row - line[3] <= 4 and start <= line[2] + 10 and end >= line[1] - 10:
                line[1], line[2], line[3] = min(line[1], start), max(line[2], end), row
                break
        else:
            lines.append([row, start, end, row])
    return [((line[0] + line[3]) // 2, line[1], line[2]) for line in lines if line[2] - line[1] >= minimum]


def raster_frames(ink: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Plot frames in pixels (x0, y0, x1, y1): pairs of long horizontal lines closed by vertical lines on both sides (most of the
    height), otherwise a left and a bottom axis meeting in a corner"""
    from scipy import ndimage  # noqa: PLC0415

    height, width = ink.shape
    minimum = int(0.12 * min(height, width))
    # scanned lines have small gaps: closed along the line direction before the runs are measured
    horizontal = long_lines(ndimage.binary_closing(ink, np.ones((1, 7), dtype=bool)), minimum)
    vertical = long_lines(ndimage.binary_closing(ink, np.ones((7, 1), dtype=bool)).T, minimum)

    def covering(x: int, top: int, bottom: int) -> Optional[int]:
        """Position of a vertical line near x over most of the height (the exact edge of the frame)"""
        lines = [v[0] for v in vertical if abs(v[0] - x) < 20 and min(v[2], bottom) - max(v[1], top) > 0.7 * (bottom - top)]
        return min(lines, key=lambda v: abs(v - x)) if lines else None

    boxes: set[tuple[int, int, int, int]] = set()
    for top in horizontal:
        for bottom in horizontal:
            if bottom[0] - top[0] < minimum:
                continue
            left, right = max(top[1], bottom[1]), min(top[2], bottom[2])
            if right - left < 0.7 * min(top[2] - top[1], bottom[2] - bottom[1]):
                continue
            left_edge, right_edge = covering(left, top[0], bottom[0]), covering(right, top[0], bottom[0])
            if left_edge is not None and right_edge is not None:
                boxes.add((left_edge, top[0], right_edge, bottom[0]))
    if not boxes:
        for axis in vertical:
            for bottom in horizontal:
                if abs(bottom[0] - axis[2]) < 20 and abs(bottom[1] - axis[0]) < 20:
                    boxes.add((axis[0], axis[1], bottom[2], bottom[0]))
    tolerance = 15

    def contains(outer: tuple[int, int, int, int], inner: tuple[int, int, int, int]) -> bool:
        return outer != inner and outer[0] <= inner[0] + 5 and outer[1] <= inner[1] + 5 and outer[2] >= inner[2] - 5 and outer[3] >= inner[3] - 5

    innermost = [box for box in boxes if not any(contains(box, other) for other in boxes)]
    unique: list[tuple[int, int, int, int]] = []
    for box in sorted(innermost, key=lambda b: (b[1] // 50, b[0])):
        if not any(all(abs(a - b) < tolerance for a, b in zip(box, other, strict=True)) for other in unique):
            unique.append(box)
    return unique


def raster_ticks(ink: np.ndarray, frame: tuple[int, int, int, int], axis: str) -> tuple[list[float], list[float]]:
    """Major and minor ticks (pixel positions) on the bottom or left edge, pointing inwards or outwards"""
    x0, y0, x1, y1 = frame
    found: dict[int, int] = {}
    # ticks at the corners count: there the frame line runs on in one direction, the tick is found in the other
    span = range(x0 - 2, x1 + 3) if axis == 'x' else range(y0 - 2, y1 + 3)
    for position in span:
        lengths = []
        for direction in (-1, 1):
            length = 0
            for step in range(3, 45):
                if axis == 'x':
                    y = y1 + direction * step
                    hit = 0 <= y < ink.shape[0] and ink[y, max(position - 1, 0) : position + 2].any()
                else:
                    x = x0 + direction * step
                    hit = 0 <= x < ink.shape[1] and ink[max(position - 1, 0) : position + 2, x].any()
                if not hit:
                    break
                length += 1
            lengths.append(length)
        accepted = [length for length in lengths if 6 <= length < 42]
        if accepted:
            found[position] = max(accepted)
    groups: list[list[int]] = []
    for position in sorted(found):
        if groups and position - groups[-1][-1] <= 2:
            groups[-1].append(position)
        else:
            groups.append([position])
    ticks = [(float(np.mean(group)), max(found[p] for p in group)) for group in groups]
    if not ticks:
        return [], []
    longest = max(length for _, length in ticks)
    return [p for p, length in ticks if length > 0.75 * longest], [p for p, length in ticks if length <= 0.75 * longest]


def outward_length(ink: np.ndarray, frame: tuple[int, int, int, int], axis: str, positions: list[float]) -> int:
    """Length of the ticks outside the frame (0 for ticks inside): the labels start beyond it"""
    x0, _, _, y1 = frame
    longest = 0
    for position in positions:
        p = round(position)
        length = 0
        for step in range(1, 45):
            hit = ink[min(y1 + step, ink.shape[0] - 1), max(p - 1, 0) : p + 2].any() if axis == 'x' else ink[max(p - 1, 0) : p + 2, max(x0 - step, 0)].any()
            if not hit:
                break
            length = step
        longest = max(longest, length)
    return longest


# ----------------------------------------------------------------------------------------------------------------------------------
# Symbols and series
# ----------------------------------------------------------------------------------------------------------------------------------
def shape_of(image: np.ndarray) -> str:
    """Shape of a filled symbol from the width of its rows (not reliable alone: decided per series by majority)"""
    rows, columns = image.shape
    fill = image.sum() / (rows * columns)
    widths = image.sum(axis=1)
    top, middle, bottom = widths[int(0.2 * rows)], widths[rows // 2], widths[int(0.8 * rows)]
    if top > 0.8 * middle and bottom > 0.8 * middle and fill > 0.85:
        return 'square'
    if top < 0.6 * bottom:
        return 'triangle'
    if bottom < 0.6 * top:
        return 'triangle-down'
    return 'circle'


def symbols(ink: np.ndarray, frame: tuple[int, int, int, int], radius: int) -> list[tuple[float, float, Optional[str], bool]]:
    """Filled symbols inside the frame: (x, y, shape or None, split)"""
    measure, morphology = require_skimage()
    x0, y0, x1, y1 = frame
    region = np.zeros_like(ink)
    region[y0 + 6 : y1 - 6, x0 + 6 : x1 - 6] = ink[y0 + 6 : y1 - 6, x0 + 6 : x1 - 6]
    from scipy import ndimage  # noqa: PLC0415

    opened = ndimage.binary_opening(region, structure=morphology.disk(radius))
    blobs = [p for p in measure.regionprops(measure.label(opened)) if p.area >= (2 * radius) ** 2 and max(p.bbox[2] - p.bbox[0], p.bbox[3] - p.bbox[1]) <= 25 * radius]
    if not blobs:
        return []
    size = float(np.median([max(p.bbox[2] - p.bbox[0], p.bbox[3] - p.bbox[1]) for p in blobs]))
    area = float(np.median([p.area for p in blobs]))
    # symbols have a typical size: remnants of letters and lines are smaller or wider in both directions, or sparsely filled
    blobs = [p for p in blobs if p.area >= 0.4 * area and min(p.bbox[2] - p.bbox[0], p.bbox[3] - p.bbox[1]) <= 1.8 * size and p.area / ((p.bbox[2] - p.bbox[0]) * (p.bbox[3] - p.bbox[1])) > 0.35]
    found: list[tuple[float, float, Optional[str], bool]] = []
    for blob in blobs:
        coords = blob.coords.astype(float)
        centred = coords - coords.mean(axis=0)
        direction = np.linalg.svd(centred, full_matrices=False)[2][0]
        extent = float(np.ptp(centred @ direction)) + 1.0
        count = max(1, round(extent / size))
        if count == 1:
            y, x = blob.centroid
            found.append((float(x), float(y), shape_of(blob.image), False))
        else:
            order = np.argsort(centred @ direction)
            for part in np.array_split(order, count):
                cy, cx = coords[part].mean(axis=0)
                found.append((float(cx), float(cy), None, True))
    return found


def predicted(track: list[tuple[float, float, Optional[str], bool]], x: float) -> float:
    """y expected at x from the last points of a track (half the local slope: curves flatten)"""
    if len(track) == 1:
        return track[-1][1]
    (xa, ya, *_), (xb, yb, *_) = track[-2], track[-1]
    return yb + (yb - ya) / max(xb - xa, 1.0) * (x - xb) * 0.5


def link(points: list[tuple[float, float, Optional[str], bool]], tolerance: float, max_step: float) -> list[list[tuple[float, float, Optional[str], bool]]]:
    """Series by continuity from left to right; pieces of one series (e.g. after a jump) are joined by their majority shape"""
    tracks: list[list[tuple[float, float, Optional[str], bool]]] = []
    for point in sorted(points):
        x, y = point[0], point[1]

        candidates = [t for t in tracks if 0 < x - t[-1][0] < max_step and abs(predicted(t, x) - y) < tolerance]
        if candidates:
            min(candidates, key=lambda t: abs(predicted(t, x) - y)).append(point)
        else:
            tracks.append([point])

    def majority(track: list[tuple[float, float, Optional[str], bool]]) -> Optional[str]:
        votes = [shape for _, _, shape, _ in track if shape]
        return max(set(votes), key=votes.count) if votes else None

    merged: list[list[tuple[float, float, Optional[str], bool]]] = []
    for track in sorted(tracks, key=lambda t: t[0][0]):
        target = next((m for m in merged if majority(m) == majority(track) and majority(track) and m[-1][0] < track[0][0]), None)
        if target is not None:
            target.extend(track)
        else:
            merged.append(list(track))
    return merged


# ----------------------------------------------------------------------------------------------------------------------------------
# Figure
# ----------------------------------------------------------------------------------------------------------------------------------
def render(page: Any) -> np.ndarray:
    image = page.to_image(resolution=RESOLUTION).original.convert('L')
    return np.array(image) < 128


def to_pt(box: tuple[int, int, int, int]) -> Box:
    return (box[0] / SCALE, box[1] / SCALE, box[2] / SCALE, box[3] / SCALE)


def raster_figure_frames(path: str, page_number: int) -> list[Box]:
    pdfplumber = require_pdfplumber()
    with pdfplumber.open(path) as pdf:
        ink = render(pdf.pages[page_number - 1])
    return [to_pt(box) for box in raster_frames(ink)]


def extract_raster(
    path: str,
    page_number: int,
    frame_index: int = 0,
    x_labels: Optional[list[float]] = None,
    y_labels: Optional[list[float]] = None,
    x_scale: Optional[str] = None,
    y_scale: Optional[str] = None,
    radius: int = 2,
) -> Figure:
    pdfplumber = require_pdfplumber()
    with pdfplumber.open(path) as pdf:
        if not 1 <= page_number <= len(pdf.pages):
            raise ExtractError(f'page {page_number} does not exist ({len(pdf.pages)} pages)')
        page = pdf.pages[page_number - 1]
        ink = render(page)
        candidates = raster_frames(ink)
        if not candidates:
            raise ExtractError(f'no plot frame found on page {page_number}')
        if frame_index >= len(candidates):
            raise ExtractError(f'frame {frame_index} does not exist ({len(candidates)} frames on page {page_number})')
        frame = candidates[frame_index]
        axes = {}
        for axis, given, scale in (('x', x_labels, x_scale), ('y', y_labels, y_scale)):
            major, minor = raster_ticks(ink, frame, axis)
            if given:
                if len(given) != len(major):
                    raise ExtractError(f'{len(given)} {axis} labels given for {len(major)} major ticks')
                order = major if axis == 'x' else major[::-1]  # labels are given from the origin: left to right, bottom to top
                pairs, source = [(p / SCALE, v) for p, v in zip(order, given, strict=True)], 'given'
            else:
                # OCR only beyond the tick marks: a tick next to a digit spoils the recognition
                outside = outward_length(ink, frame, axis, major + minor) + 4
                # one line of labels (axis titles further out are excluded)
                region_px = (frame[0] - 60, frame[3] + outside, frame[2] + 60, frame[3] + outside + 70) if axis == 'x' else (frame[0] - 170, frame[1] - 30, frame[0] - outside, frame[3] + 30)
                labels = ocr_labels(page, to_pt(region_px))
                closest: dict[float, tuple[float, float]] = {}  # tick -> (distance, value): one label per tick
                for x, y, value in labels:
                    coordinate = (x if axis == 'x' else y) * SCALE
                    ticks = major + minor
                    tick = min(ticks, key=lambda t: abs(t - coordinate)) if ticks else None
                    if tick is not None and abs(tick - coordinate) < 25 and (tick not in closest or abs(tick - coordinate) < closest[tick][0]):
                        closest[tick] = (abs(tick - coordinate), value)
                pairs, source = sorted((tick / SCALE, value) for tick, (_, value) in closest.items()), 'ocr'
            axes[axis] = calibrate([p / SCALE for p in major], pairs, source, scale)
    found = symbols(ink, frame, radius)
    if not found:
        raise ExtractError(f'no filled symbols found in frame {frame_index} (open symbols and lines are not supported for scans yet)')
    tolerance = 0.045 * (frame[3] - frame[1])
    series = []
    for index, track in enumerate(link(found, tolerance, 0.25 * (frame[2] - frame[0]))):
        votes = [shape for _, _, shape, _ in track if shape]
        majority = max(set(votes), key=votes.count) if votes else 'unknown'
        points = []
        for x, y, shape, split in sorted(track):
            flag = 'split' if split else ('shape' if shape != majority else None)
            points.append(Point(x / SCALE, y / SCALE, flag=flag))
        series.append(Series(f'{majority}-filled-{index}', 'marker', points))
    return Figure(page_number, to_pt(frame), axes['x'], axes['y'], series, (len(raster_ticks(ink, frame, 'x')[0]), len(raster_ticks(ink, frame, 'y')[0])))


def is_scanned(path: str, page_number: int) -> bool:
    """Page without vector graphics but with an image (a scan)"""
    pdfplumber = require_pdfplumber()
    with pdfplumber.open(path) as pdf:
        if not 1 <= page_number <= len(pdf.pages):
            raise ExtractError(f'page {page_number} does not exist ({len(pdf.pages)} pages)')
        page = pdf.pages[page_number - 1]
        return bool(page.images) and len(page.curves) + len(page.rects) < 5 and len(page.lines) < 20
