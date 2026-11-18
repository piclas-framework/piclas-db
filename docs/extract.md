# Data from figures and tables

`piclas-db extract` reads the data series of a figure in a PDF of a paper that is in the store (`import --literature`). In a vector
figure, markers, error bars, lines and ticks are drawing operations with exact coordinates, so the values are read rather than
estimated from pixels. Scanned figures follow in a later version.

```bash
pip install "piclas-db[extract]"           # pdfplumber; OCR of axis labels drawn as outlines needs the tesseract binary
piclas-db extract santanna-2025 --page 4 --list
piclas-db extract santanna-2025 --page 4 --figure 3 --name fig3 \
    --x-unit a.u. --x-quantity "O- velocity" --mass-amu 15.9994 --y-unit A^2 --by "Name" -o work/
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
