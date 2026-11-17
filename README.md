[![CI](https://github.com/piclas-framework/piclas-db/actions/workflows/ci.yml/badge.svg)](https://github.com/piclas-framework/piclas-db/actions/workflows/ci.yml)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
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
> piclas-db is under development (version 0.x). The command-line interface is in place, the commands are implemented step by step
> (see [CHANGELOG.md](CHANGELOG.md)).

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
| `piclas-db guide lxcat:biagi-ar` | Step-by-step guide for a manual download | planned (WP1) |
| `piclas-db import --source-dir ~/Downloads` | Identify by content, validate, sort into the local store | planned (WP1) |
| `piclas-db fetch [--mirror <private repo>]` | Download where the source terms allow it, restore from a private mirror | planned (WP1) |
| `piclas-db push` | Back up the local store to the private mirror | planned (WP1) |
| `piclas-db build -o database.h5` | Build the database from the local store | planned (WP1) |
| `piclas-db export database.h5 -o tables/` | Write the `.h5` containers to ASCII tables | planned (WP2) |
| `piclas-db plot Ar-electron --compare` | Plot data from original files, ASCII tables or `.h5` | planned (WP3) |
| `piclas-db reservoir --species Ar --temps 1e3:1e5` | `parameter.ini` files for a reservoir parameter study | planned (WP4) |
| `piclas-db check old.h5` | Detect the layout, report corrupt or inconsistent data ([rules](docs/checks.md)) | **available** |
| `piclas-db diff old.h5 new.h5` | Changed datasets and attributes, and by how much ([details](docs/diff.md)) | **available** |
| `piclas-db migrate old.h5 -o new.h5` | Convert a legacy layout to the current layout (new file) | planned |
| `piclas-db rebuild old.h5 -o new.h5` | Re-download the sources of an existing database, rebuild it (old or new layout) and compare | planned |

## Where the data comes from
For every dataset a database needs (`build`, `rebuild`), piclas-db looks in the following places, in this order, and only
moves on to the next one if the dataset was not found:

1. **Local store**: original files already on your machine.
2. **Private repository**: the organisation's private backup of the original files, accessed via SSH with your own git
   permissions. Found files are copied into the local store.
3. **Automatic download**: only from sources whose terms allow it (e.g. the IAEA CollisionDB API).
4. **Guided manual download**: step-by-step instructions for the source website (e.g. LXCat, ATcT, IAEA ALADDIN), followed
   by `piclas-db import`.

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
[CHANGELOG.md](CHANGELOG.md).

# Citing piclas-db
If you use piclas-db, please cite it as given in [CITATION.cff](CITATION.cff) (GitHub shows the citation under "Cite this
repository"). Since piclas-db does not contain any data, please also cite the original data sources of your database, e.g. the
LXCat databases, NIST or ATcT, as stated in the references stored in the database.

# License and contributors
piclas-db is free software under the [GNU General Public License v3.0](LICENSE) or later. The contributors are listed in
[CONTRIBUTORS.md](CONTRIBUTORS.md). The tool is based on the species and cross-section database tools previously maintained in
the [PICLas repository](https://github.com/piclas-framework/piclas).
