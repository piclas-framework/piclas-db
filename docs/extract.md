# Data from figures and tables

`piclas-db extract` reads the data series of a figure in a PDF of a paper that is in the store (`import --literature`). In a vector
figure, markers, error bars, lines and ticks are drawing operations with exact coordinates, so the values are read rather than
estimated from pixels. Scanned figures are read from the image (see below).

```bash
python -m pip install -e ".[extract]"     # in the clone: pdfplumber, scikit-image; OCR needs the tesseract binary (e.g. apt install tesseract-ocr)
piclas-db extract santanna-2025 --page 4 --list
piclas-db extract santanna-2025 --page 4 --figure 3 --name fig3 \
    --x-unit a.u. --x-quantity "O- velocity" --mass-amu 15.9994 --target-mass-amu 31.998 --y-unit A^2 --by "Name" -o work/
# without Tesseract: give the labels of the major ticks, e.g. --x-labels 0.04,0.06,0.08,0.1,0.12,0.14,0.16 --y-labels 0,5,10,15,20
piclas-db literature add work/fig3-square-open-black.extraction.yaml     # per series, review pending
```

## What is read

| Step | How | Shown in the record |
| --- | --- | --- |
| frame | innermost rectangle (or box of four lines) that contains markers or lines; `--frame` selects one of several | `parameters.frame_pt` |
| ticks | short lines on the bottom and left edge; the longest are the major ticks | |
| labels | text next to the ticks, superscripts as powers of ten (`10⁻²⁰`, `6×10⁻²¹`); labels drawn as glyph outlines by OCR; otherwise `--x-labels` / `--y-labels` | `calibration.*.labels_from`, `labels` |
| scale | linear or logarithmic from the labels (the better fit), or `--x-scale` / `--y-scale` | `calibration.*.scale` |
| calibration | fit through the labelled ticks; pairs of labels propose fits and the one most labels agree with wins, so single OCR errors are rejected | `calibration.*.residual` |
| series | markers grouped by shape (square, circle, triangle), fill and colour; lines with many points as separate series | `parameters.series` |
| error bars | vertical lines through the marker centres, written as relative uncertainty | `result.error_bars` |

Every series becomes a CSV with the values in axis units and an extraction record (`method: vector`, calibration, parameters,
pdfplumber and Tesseract versions). A review image (`p<page>-f<frame>-review.png`) shows the points, error bars and labelled ticks on
the figure.

The x axis can be an energy (`eV`, `keV`) or a velocity (`m/s`, `cm/s`, `a.u.`); a velocity is converted to the kinetic energy in
the laboratory frame with `--mass-amu`. Values below zero that are zero within their error bar are used as zero (noted in the record).

## Example: Sant'Anna et al. 2025, Fig. 3

Both series (BAT, open squares; SGR, filled squares) are read with 15 points each and 27 error bars; the x labels by OCR with a
residual of 1e-16, the y labels with 6e-4 Å². Converted with the O⁻ mass, the velocities give the beam energies of the
experiment (0.50, 0.99, 1.24, 1.49, 1.98 keV, …), which confirms the calibration independently.

## Scanned figures

Pages without vector graphics (scans) are recognized automatically (or with `--raster`):

```bash
piclas-db extract tsuji-1989 --page 3 --list                     # frames found on the page
piclas-db extract tsuji-1989 --page 3 --frame 1 --figure 5 --name fig5 \
    --x-unit "1e5 m/s" --mass-amu 28.0855 --y-unit "1e-15 cm^2" -o work/
```

| Step | How |
| --- | --- |
| image | page rendered at 300 dpi, black and white |
| frame | pairs of long horizontal lines closed by vertical lines over most of the height (pieces of skewed or broken scan lines are joined), otherwise a left and a bottom axis; edges from the vertical lines |
| ticks | short lines on the bottom and left edge, inside or outside, also at the corners |
| labels | OCR beyond the tick marks, one line of labels per axis, one label per tick; the calibration tolerance follows the step between labels, so misread labels (`2.0` for `2.4`, `20.0` for `2.0`) are rejected; or `--x-labels` / `--y-labels` from the origin (left to right, bottom to top) |
| symbols | filled symbols remain after an opening with radius `--symbol-radius` (default 2 pixels); remnants of letters and lines are removed by size and fill; touching symbols are split along their direction |
| series | linked from left to right by continuity, named by the majority of the recognized shapes (square, circle, triangle) |
| flags | `split` (from touching symbols) and `shape` (shape differs from the series) are listed in the record notes and marked orange in the review image |

The record has `method: raster`, the resolution and symbol radius, the digitization accuracy (one pixel in axis units) and the
scikit-image and Tesseract versions.

### Open symbols, crossing curves and difficult scans

* **Open symbols** (○ △ □) are filled before the opening and named `circle-open` etc.; filled and open symbols are linked
  separately, and short open tracks (letters such as o, e, a in the figure) are dropped. Crosses (×) and curves without symbols are
  not read.
* **Crossing curves**: `--seeds "x,y;x,y,x2,y2"` (axis values) gives one curve per seed. A curve starts at the symbol nearest to
  the seed and follows symbols to the right along the local slope, keeping its kind (filled or open) and taking the next symbol
  where several fit; a second point gives the direction where the first step is ambiguous.
* **Axes not found** (dotted or broken in the scan): `extract --list` writes a grid image (`p<page>-grid.png`, 10 pt grid); read
  the frame (`--frame-box x0,y0,x1,y1`) and calibration points (`--x-points "pt=value,…"`, `--y-points …`, with `--y-scale log`
  for logarithmic axes) from it. Symbols outside the calibrated range are ignored.

Matić and Čobić 1971, Fig. 1 (two panels, logarithmic, 1-bit scan, dotted axes, about 28 crossing curves): with the frame and
calibration points from the grid image and one seed per curve, the C⁻ + N₂ one-, two- and three-electron loss curves agree with the
earlier prototype within 1 %, including the three-electron points at 8 and 10 keV that the prototype needed a second look for. The
small open symbols (○ Ne, △ Ar) of this scan are broken by the 1-bit scan and not detected reliably; such curves are entered by hand
(`literature template`).

Tsuji et al. 1989, Fig. 5 (Si⁻, C⁻, O⁻ in N₂): all 36 points in the right series, fully automatic (x labels 1–8, y labels with
two misread labels rejected); they agree with the earlier prototype within 0.003 × 10⁻¹⁵ cm²; two points split from touching symbols
and two shape mismatches are flagged.

## Tables

```bash
piclas-db extract yoon-2008 --page 14-15 --table 12 --by "Name" -o work/     # pages: a table may continue on the next page
piclas-db literature add work/table12-c1.extraction.yaml
```

| Step | How |
| --- | --- |
| words | text layer of the PDF; pages without one (scans) by OCR with Tesseract, or always with `--ocr` |
| caption | `TABLE 12.`, `TABLE12.`, `Table 2:`; references in the running text ("listed in Table 7.") are tried as well and discarded when no table follows; upper-case captions first |
| layout | on two-column pages (no word near the caption crosses the middle) only the column of the caption |
| table | data rows (mostly numbers) below or above the caption, header lines on the caption side; continuation pages (`—Continued`) are joined |
| columns | separated where no word of a data row lies; a label split into two columns is joined again |
| numbers | `9.70E−07`, `9.5185(-4)` (= 9.5185e-4), `0.003 51` (digit groups), Unicode minus, footnote marks |
| units | from the header: `(eV)`, `(keV)`, `(10−17 cm2)` → `1e-17 cm^2`, `Å2` → `A^2`; otherwise `--x-unit` / `--y-unit` |

Every table is written as raw CSV (`table<n>-table.csv`, header and all cells). If the first column is an increasing energy, every
further column becomes a series (`table<n>-c<column>`) with an extraction record (`method: text` or `ocr`, table, pages, column
header, units). Tables without an energy column, such as fit parameters (Janev et al. 2003), are kept as raw tables; using fit
formulas follows in a later version.

All twelve data tables of Yoon et al. 2008 (Tables 1–5, 7–9, 11–14, including those continued on the next page, two-column layout,
several columns with different units) are read with the correct number of rows; Table 13 is identical to the values entered by
hand. The three `SpeciesDatabase.h5` datasets that cite Yoon et al. (`H-electron-H`, `H2Ion1-electron-electron`,
`H-electron-electron-HIon1`) are the same cross-sections as Tables 11 and 13, on a different energy grid (with additional points,
e.g. at the threshold).

## Running extractions again

```bash
piclas-db extract --redo yoon-2008/table13-c1 -o redo/          # or PAPER/DATASET@sha256 for one stored version
```

Every record of `extract` (from 0.21.0) contains the options it was made with (`parameters.command`); for older records they are
taken from the record (page, frame, labels given, seeds, units). The extraction runs again with the current version of piclas-db and
is compared point by point with the stored one (identical, or the largest change in axis units and, where the value is significant,
relative). The new record keeps what was entered by hand (description, assignment, units, masses), names the stored version under
`supersedes` and is stored like any extraction: `literature add` (review pending); `build` then uses the newest reviewed version.
If the new record does not meet the rules of the current version (e.g. a velocity axis without target mass before 0.19.0), `--redo`
says what to complete. Extractions entered by hand (`manual`, formulas) are not run again.

Stored extractions of the test papers, run again with 0.21.0: Yoon Table 13 identical, Tsuji Fig. 5 within 0.02 %, Sant'Anna Fig. 3
within 0.002 Å² (more axis labels read by the improved OCR).
