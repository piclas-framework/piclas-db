[![CI](https://github.com/piclas-framework/piclas-db/actions/workflows/ci.yml/badge.svg)](https://github.com/piclas-framework/piclas-db/actions/workflows/ci.yml)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.24324389.svg)](https://doi.org/10.5281/zenodo.24324389)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)](pyproject.toml)

# piclas-db

piclas-db builds, checks and converts the species and cross-section databases (`database.h5`) that
[PICLas](https://github.com/piclas-framework/piclas) reads in for collision, chemistry and plasma models. The databases are created
from the original sources, e.g. [LXCat](https://www.lxcat.net), [NIST](https://www.nist.gov/pml/atomic-spectra-database) or
[ATcT](https://atct.anl.gov), and written in the HDF5 container layout of the PICLas `SpeciesDatabase.h5`.

> [!IMPORTANT]
> This repository contains the **tool only, no data**. Many data providers do not allow the redistribution of their data and ask
> users to download it directly from them. Therefore, every user builds `database.h5` locally from their own downloads. piclas-db
> guides you through the download, stores the original files in a local store and can back it up to a private repository.

> [!NOTE]
> piclas-db is under development (version 0.x). All commands are implemented; the interface and file layouts may still change
> until version 1.0.0 (see [CHANGELOG.md](CHANGELOG.md)).

# Table of Contents

- [Installation](#installation)
- [Usage](#usage)
- [Development](#development)
- [Versioning](#versioning)
- [Citing piclas-db](#citing-piclas-db)
- [License and contributors](#license-and-contributors)

# Installation
1.  **Optional: Create and activate a virtual environment**
    ```bash
    python -m venv venv
    source venv/bin/activate
    ```

2.  **Install piclas-db** from the repository (editable installation for development)
    ```bash
    git clone https://github.com/piclas-framework/piclas-db.git
    cd piclas-db
    python -m pip install -e ".[dev]"
    ```

# Usage
Show the available commands and the version
```bash
piclas-db --help
piclas-db -v
```

| Command | Description | Status |
| --- | --- | --- |
| `piclas-db guide lxcat/biagi-v7.1/ar` | Step-by-step guide for a manual download ([details](docs/rebuild.md)) | **available** |
| `piclas-db import --source-dir ~/Downloads` | Identify by content, validate, copy into the local store ([details](docs/store.md)) | **available** |
| `piclas-db config [--init]` | Configuration file: store, private repository, defaults for options ([details](docs/configuration.md)) | **available** |
| `piclas-db store [--verify]` | List the local store, verify the files against their sha256 | **available** |
| `piclas-db fetch [--mirror <private repo>] [--need ...]` | Clone or update the store from the private repository, locate required files ([details](docs/store.md#private-repository)) | **available** |
| `piclas-db push` | Back up the local store to the private repository | **available** |
| `piclas-db literature template\|add\|review\|list` | Data from papers (tables, figures, fit formulas) with extraction record and review ([details](docs/literature.md)) | **available** |
| `piclas-db extract paper --page 4 [--table 12] -o work/` | Read the data series of a vector figure, or a table, into extraction records ([details](docs/extract.md)) | **available** |
| `piclas-db build recipe.yaml -o database.h5` | Build a database from the original files according to a recipe ([details](docs/build.md)) | **available** |
| `piclas-db export database.h5 -o tables/` | Write a database of any layout as ASCII tables ([details](docs/migrate.md)) | **available** |
| `piclas-db plot db.h5 lxcat.txt --pair Ar-electron --compare` | Plot σ(E), k(T) or electronic levels from any sources ([details](docs/plot.md)) | **available** |
| `piclas-db reservoir db.h5 --pair Ar-electron --energies 16 20 50 -o study/` | PICLas reservoir study and its evaluation against the database ([details](docs/reservoir.md)) | **available** |
| `piclas-db reservoir [db.h5] --regressioncheck <piclas>/regressioncheck/NIG_Reservoir_single_core` | Compare the reference results of the PICLas reservoir regression checks with a database ([details](docs/reservoir.md#regression-checks-of-piclas)) | **available** |
| `piclas-db check old.h5` | Detect the layout, report corrupt or inconsistent data ([rules](docs/checks.md)) | **available** |
| `piclas-db diff old.h5 new.h5` | Changed datasets and attributes, and by how much ([details](docs/diff.md)) | **available** |
| `piclas-db migrate old.h5 -o new.h5` | Convert any layout or ASCII tables to the current layout ([details](docs/migrate.md)) | **available** |
| `piclas-db rebuild old.h5 -o new.h5` | Rebuild an existing database from the original files and compare ([details](docs/rebuild.md)) | **available** |

## Tutorials
[Getting started](docs/tutorials/T1-getting-started.md), [adding data](docs/tutorials/T3-adding-data.md), [the private source repository](docs/tutorials/T4-private-repository.md); overview in [docs/tutorials](docs/tutorials/README.md).

# Where the data comes from
For every dataset a database needs (`build`, `rebuild`), piclas-db looks in the following places, in this order, and only
moves on to the next one if the dataset was not found:

1. **Local store**: original files already on your machine.
2. **Private repository**: the organisation's private backup of the original files, accessed via SSH with your own git
   permissions. Found files are copied into the local store.
3. **Automatic download**: only from sources whose terms allow it (no provider supported yet; a candidate is the IAEA
   CollisionDB API).
4. **Guided manual download**: step-by-step instructions for the source website with `piclas-db guide` (LXCat, NIST ASD),
   followed by `piclas-db import`. Data that only exist in papers are entered from the paper with an extraction record and a
   review ([data from papers](docs/literature.md)).

Files obtained in steps 3 and 4 are added to the private repository step by step: each imported file is committed with its
provenance (source, dataset, retrieval date, sha256) and pushed with `piclas-db push`, if you have write access. Users without
access to the private repository continue with steps 1, 3 and 4 only.

The layout of `database.h5` (what PICLas reads and what piclas-db writes) is specified in [docs/layout.md](docs/layout.md).

The database is used in PICLas with
```ini
Particles-Species-Database = database.h5
```

# Development
piclas-db uses [prek pre-commit](https://prek.j178.dev/quickstart/) for maintaining code quality. The hooks run
[Ruff](https://docs.astral.sh/ruff/) (linter and formatter), [ty](https://github.com/astral-sh/ty) (type checker),
[Vulture](https://github.com/jendrikseipp/vulture) (dead code), [gitleaks](https://github.com/gitleaks/gitleaks) (secrets) and
checks against large files, which keep data out of the repository. Install the hooks with
```bash
prek install
```
and run them on all files with
```bash
prek run --all-files
```
The tests use synthetic data only and are executed with
```bash
pytest
```
The same checks run in the [GitHub Actions CI](.github/workflows/ci.yml) for every push and pull request.

# Versioning
piclas-db starts with version 0.1.0 and increments the minor version (0.x.0) with each development step. Version 1.0.0 is
released once the tool is feature complete. The version is defined in `pyproject.toml` only and changes are listed in
[CHANGELOG.md](CHANGELOG.md). Releases are created by pushing a tag `v<version>` ([release checklist](CONTRIBUTING.md#release-checklist));
every release is archived by [Zenodo](https://zenodo.org) with a DOI.

# Citing piclas-db
If you use piclas-db, please cite it as given in [CITATION.cff](CITATION.cff) (GitHub shows the citation under "Cite this
repository"). The DOI [10.5281/zenodo.24324389](https://doi.org/10.5281/zenodo.24324389) refers to all versions and resolves to
the latest one; every release also has its own DOI on Zenodo. Since piclas-db does not contain any data, please also cite the original data sources of your database, e.g. the
LXCat databases, NIST or ATcT, as stated in the references stored in the database.

# License and contributors
piclas-db is free software under the [GNU General Public License v3.0](LICENSE) or later. The contributors are listed in
[CONTRIBUTORS.md](CONTRIBUTORS.md). The tool is based on the species and cross-section database tools previously maintained in
the [PICLas repository](https://github.com/piclas-framework/piclas).
