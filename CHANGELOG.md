# Changelog

piclas-db starts with version 0.1.0. The minor version (0.x.0) is incremented with each development step until the tool is
feature complete, which will be released as version 1.0.0. The version is defined in `pyproject.toml` only.

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
