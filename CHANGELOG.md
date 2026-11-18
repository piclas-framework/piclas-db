# Changelog

piclas-db starts with version 0.1.0. The minor version (0.x.0) is incremented with each development step until the tool is
feature complete, which will be released as version 1.0.0. The version is defined in `pyproject.toml` only.

## 0.18.0

* `piclas-db extract` reads scanned figures with filled symbols (`piclas_db/extract/raster.py`, documented in `docs/extract.md`):
  frames from joined line pieces, ticks also at the corners, OCR of the labels beyond the tick marks, symbols by morphological
  opening, touching symbols split, series by continuity and majority of the shapes, flags for split symbols and shape mismatches in
  the record and the review image; scans are recognized automatically (`--raster`, `--symbol-radius`)
* Axis calibration: tolerance from the step between labels, so misread labels are rejected; OCR combines two Tesseract modes with
  a character whitelist; labels given on the command line count from the origin (y bottom to top)
* Optional dependency group `extract`: scikit-image

## 0.17.0

* `piclas-db extract PAPER --page 14-15 --table 12` reads tables (`piclas_db/extract/table.py`, documented in `docs/extract.md`):
  text layer or OCR (Tesseract) for scans, caption above or below, two-column pages, continuation pages joined, columns from the
  gaps between words, numbers in paper notations (`9.70E−07`, `9.5185(-4)`, digit groups), units from the column headers; raw
  table CSV, and for tables with an energy column one series with extraction record per column
* Checked with all twelve data tables of Yoon et al. 2008 and parameter tables of Janev et al. 2003; the `SpeciesDatabase.h5`
  datasets citing Yoon et al. are Tables 11 and 13
* `extract --page` accepts page ranges

## 0.16.0

* `piclas-db extract PAPER --page N` reads the data series of vector figures (`piclas_db/extract/vector.py`, documented in
  `docs/extract.md`): plot frame, ticks, axis labels from the text (superscripts as powers of ten) or by OCR or from the command line,
  linear or logarithmic scale, robust calibration with residual, markers grouped by shape, fill and colour, lines, error bars; writes
  CSV files and extraction records (`method: vector`) and a review image
* Literature: velocity axes (`m/s`, `cm/s`, `a.u.`) converted to energy with `mass_amu`; values below zero that are zero within their
  uncertainty are used as zero
* Optional dependency group `extract` (pdfplumber)

## 0.15.0

* `literature` provider (`piclas_db/literature.py`, documented in `docs/literature.md`): papers (PDF) into the store with
  `import --literature KEY --doi … --reference …`; `piclas-db literature template | add | review | list` to enter tables as printed
  with an extraction record (source with paper sha256, page, table/figure; method; units; accuracy; piclas-db version and
  environment; review status); checks against typing errors, unknown units and a wrong paper
* Recipes: section `literature` (pair, kind, key or threshold); `build` uses approved extractions only (`--allow-unreviewed`),
  datasets carry citation with DOI, table and page, extraction and review; new check rule `literature-unreviewed`
* Store: meta files can be updated (reviews), committed in a private-repository store

* Documentation: outdated "planned" statements removed (`guide` exists since 0.9.0, no automatic download yet), `reservoir
  --regressioncheck` in the command table of `README.md`; `fetch --need` names the `guide` command for missing files

## 0.14.1

* Concept DOI 10.5281/zenodo.24324389 (all versions) in `CITATION.cff` and as badge in `README.md`; first release 0.14.0 archived
  on Zenodo (10.5281/zenodo.24324390)
* Release workflow builds with Python 3.14 (no h5py wheels for Python 3.15 yet)
* `.gitignore`: store directories anchored to the repository root (`piclas_db/sources/` was ignored)

## 0.14.0

* Release workflow (`.github/workflows/release.yml`): on a tag `v<version>` it checks that tag, `pyproject.toml` and `CHANGELOG.md`
  agree, builds and tests the wheel (including `guides.yaml` and the CLI), creates the GitHub release with the changelog section as
  release notes; Zenodo archives every release with a DOI; optional PyPI publishing (repository variable `PUBLISH_PYPI`)
* `CONTRIBUTING.md` with development setup, versioning and release checklist

## 0.13.0

* `piclas-db reservoir --regressioncheck DIRECTORY` compares the reference results of the PICLas `NIG_Reservoir` regression checks
  with the database of each check or with any other database (`piclas_db/regressioncheck.py`); the expected rates take into account
  the thermal motion of the background, the rotational energy of molecular reactants (PICLas evaluates reaction cross-sections at
  the collision energy including internal energy), the zero point at the heat of reaction and the collision probability per time
  step; all 61 comparisons of the six XSec chemistry checks agree within 4.2 %
* `rebuild` identifies cross-sections with an LXCat header but without database name by species, process and update time in the
  LXCat downloads of the store

## 0.12.0

* Provenance in every written database (`piclas_db/provenance.py`, documented in `docs/layout.md`): root attributes with layout
  format version, piclas-db version and commit, UTC creation time, command, embedded recipe with sha256, every original file with
  its store path, sha256 and retrieval date, and the input file of `migrate`/`rebuild` with its sha256
* `piclas-db check` shows the provenance; new rules `provenance-file`, `provenance-format`, `provenance-recipe`
* `piclas-db rebuild` uses the embedded recipe of files built by piclas-db (`--derive` for the old behaviour)
* String metadata lists are written as UTF-8 string arrays

## 0.11.1

* `reservoir`: first study with PICLas (Ar-electron, 16-100 eV) passes, with a systematic deviation of -1.7 % to -2.5 %, consistent
  with the collision probability 1 - exp(-n sigma g dt) at 0.05 per time step; default lowered to 0.01, new option
  `--collision-probability`; repeated with 0.01: -0.7 % to -1.9 %, all within the counting statistics (validation with PICLas done)
* `reservoir --evaluate` marks points beyond three standard deviations as `(systematic?)` and reports deviations in the same direction
* Row count in shapes written as `n_rows` instead of `N` (polynomial degree in PICLas)

## 0.11.0

* `piclas-db reservoir` (WP4, `piclas_db/reservoir.py`, documented in `docs/reservoir.md`) generates PICLas reservoir studies after
  the `NIG_Reservoir` regression checks: monoenergetic beam (`--energies`) or Maxwell distribution (`--temperatures`), one
  `parameter.ini` per point, single-cell `hopr.ini`, run script and `study.yaml` with the expected rate coefficients; time step and
  number of steps from the collision probability and the aimed number of counted reactions
* `piclas-db reservoir --evaluate` compares the rate coefficients in `PartAnalyze.csv` with the database (tolerance or three
  standard deviations of the counting statistics), writes a table and `rates.png`
* Expected rates take into account that PICLas prepends σ = 0 at the heat of reaction
* New check rule `xsec-products-missing` (e.g. XeIon2 cross-sections in `SpeciesDatabase.h5` without the species XeIon2)
* All planned commands are implemented; the placeholder for planned commands is removed

## 0.10.0

* `piclas-db plot` (WP3, `piclas_db/plot.py`, documented in `docs/plot.md`): cross-sections σ(E), Maxwellian rate coefficients k(T)
  (`--rate`) and electronic levels (`--species`) from any combination of database files, table directories and original LXCat /
  NIST ASD downloads; same cross-section in the same color in every source, `--compare` adds the relative deviation from the first
  source; output as PNG, PDF or SVG
* Original downloads can be read directly (`piclas_db/sources/any.py`), also by `piclas-db diff`
* Rate coefficient integral tested against the analytic solutions for a constant and a step cross-section
* New dependency: matplotlib

## 0.9.0

* `piclas-db guide` prints step-by-step download instructions per provider (from `piclas_db/guides.yaml`), for given files or for
  the files of a recipe missing in the store (`--recipe`)
* `piclas-db rebuild OLD -o NEW` derives a recipe from the provenance of an old file (LXCat references and headers, NIST levels),
  locates the original files (guide for missing ones), builds the database, copies what cannot be rebuilt and compares with the
  old file (`piclas_db/rebuild.py`, documented in `docs/rebuild.md`)
* Readers: references stored on a cross-section group (e.g. `ELECTRONIC`) apply to its datasets
* Recipes may contain `notes`

## 0.8.0

* `piclas-db build RECIPE -o OUTPUT.h5` builds a database from the original files in the store (`piclas_db/build.py`, documented in
  `docs/build.md`); missing files are located in the private repository or listed for a manual download; the result is checked
* Recipes (`piclas_db/recipe.py`): selection of LXCat databases, species, processes and type mappings per collision pair, NIST ASD
  levels per species, own species and reaction attributes; files can be pinned by sha256
* LXCat mapping fixes the classification of the former `create_xsec_db_lxcat.py` (rotational, vibrational and electronic excitation,
  several ionization channels, ion-neutral data); reference, LXCat header, threshold and source file with sha256 on every dataset
* NIST ASD levels converted to K with exact constants and sorted
* Example recipe `recipes/gec-argon.yaml`: reproduces the electron data of the GEC tutorial file exactly

## 0.7.0

* The local store can be a clone of the private repository (`piclas_db/git.py`, `piclas_db/resolve.py`, documented in
  `docs/store.md`): access with the user's own SSH key, git runs non-interactively
* `piclas-db fetch --mirror URL` clones the private repository (also when it is still empty) or updates the store; an existing local
  store is adopted, its files are added and the old directory is kept as a backup
* Every import is committed separately with its provenance in the message; `index.yaml` is excluded from git
* `piclas-db push` backs up the store, refuses changed files
* `piclas-db fetch --need PROVIDER/DATASET[@SHA]` locates required files: local store, private repository, automatic download
  (none yet), manual download

## 0.6.0

* Local store of original files (`piclas_db/store.py`, documented in `docs/store.md`): files kept byte for byte under
  `<provider>/<dataset>/<retrieved>_<sha8>`, `meta.yaml` with provenance and sha256, generated `index.yaml`; location from
  `--store`, `$PICLAS_DB_STORE` or `~/.local/share/piclas-db/store`
* `piclas-db import` identifies files by their content and validates them: LXCat cross-sections (including ion-neutral blocks) and
  swarm data, NIST ASD level exports (CSV, tab or text), own data with `--custom`; duplicates (same sha256) are detected
* `piclas-db store` lists the store, `--verify` checks all files against their sha256
* Parsers for LXCat downloads (`piclas_db/sources/lxcat.py`) and NIST ASD levels (`piclas_db/sources/nist.py`)

## 0.5.0

* Writer for the current layout (`piclas_db/writer.py`): strings read by PICLas as fixed-length, null-padded ASCII (255
  characters), logicals as integers, all data as float64, one metadata scheme
* `piclas-db migrate SOURCE -o OUTPUT.h5` converts any layout or ASCII tables into the current layout; `--fix` renames typos in
  group and attribute names and sorts electronic levels, `--canonical-products` renames reaction cross-sections to the conventional
  product order; colliding renames are skipped and reported; the result is checked
* `piclas-db export SOURCE -o DIRECTORY` writes ASCII tables (YAML and CSV, `piclas_db/tables.py`); tables are read by all commands
* Round trip h5 -> tables -> h5 reproduces values, attributes and data types exactly
* `diff`: entries with coinciding keys (e.g. thresholds `14` and `14.0`) are matched by their exact names
* New dependency: PyYAML

## 0.4.0

* `piclas-db diff A.h5 B.h5` compares two databases of any layout (`piclas_db/compare.py`, documented in `docs/diff.md`):
  species, electronic levels, attributes, reactions, cross-sections, diffusion and surface data
* Matching across layouts: collision pairs independent of their order, thresholds as numbers, reaction products independent of their
  order, group names with typos; renamed entries are reported
* Result classes identical, numerically different, scaled, different structure, attributes differ, renamed, only in A/B; references
  naming different sources are marked; float32-aware tolerance (`--rtol`); only shared categories unless `--all`; `--json`

## 0.3.0

* `piclas-db check` applies content rules to all layouts (`piclas_db/rules.py`, documented in `docs/checks.md`): species attributes,
  electronic levels (ground state, NIST ground-state degeneracies, cm⁻¹/K units, ionization energy), reaction attributes and
  conservation, cross-section names, thresholds, product order and ambiguous channels, data values, duplicates, float32 storage
  and provenance
* Severities ERROR, WARNING and INFO; exit code 1 on errors; options `--info` and `--json`
* Reference values from NIST ASD (ionization energies, ground-state degeneracies) in `piclas_db/reference.py`

## 0.2.0

* Specification of the PICLas database layout derived from the PICLas read paths (`docs/layout.md`)
* Layout-independent data model (`piclas_db/model.py`): species, reactions, collision pairs and cross-sections, diffusion and
  surface data, provenance collected from all attribute variants found in existing files
* Readers for the current species database, legacy XSec and legacy electronic state databases (`piclas_db/readers.py`); quirks of
  old files (unknown group names, empty groups, placeholders, float32 data, 2D string attributes) are preserved for the checks
* `piclas-db check` reads the complete file into the data model and prints a summary

## 0.1.0

* Repository setup: license, contributors, citation file, pre-commit hooks (ruff, ty, vulture, gitleaks), GitHub Actions CI
* Command-line interface `piclas-db` with all planned sub-commands (`-v/--version`, `-h/--help`)
* `piclas-db check`: file integrity (all datasets readable) and layout detection (current species database, legacy XSec and
  legacy electronic state databases)
