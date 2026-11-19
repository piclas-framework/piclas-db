# Data sources

Where the data for PICLas databases can be collected, what piclas-db reads, and which sources can be queried automatically. Every
original file goes into the **store**, i.e. into the private source repository of the group (tutorial [T4](tutorials/T4-private-repository.md)):
downloads, extractions from papers and own data, all in one place. Nothing of it is published with piclas-db; the terms of every
source apply.

Status of the table: November 2026. Check the terms of a source before automated use.

## Overview

| Source | Data | Website | Access | piclas-db |
| --- | --- | --- | --- | --- |
| **LXCat** (v2) | electron and ion cross-sections (many databases: Biagi, Phelps, Hayashi, Itikawa, …), swarm data | https://www.lxcat.net | web download: TXT, XML, ZIP | **reads** TXT, XML, ZIP; `guide`, `import`; TXT = XML checked |
| **LXCat 3** | same data, JSON, versioned, permalinks | https://github.com/LXCat-project/LXCat (demo: https://demo.lxcat.net) | **API** (token, developer role); beta | planned (JSON, API) |
| **NIST ASD** | atomic energy levels, ionization energies | https://physics.nist.gov/PhysRefData/ASD/levels_form.html, https://physics.nist.gov/PhysRefData/ASD/ionEnergy.html | web form ("CSV (text)", "ASCII (text)") | **reads** levels (CSV, tab, text) with the ionization limit; **downloads automatically** (levels form as URL) |
| **NIST Chemistry WebBook** | thermochemistry (JANAF), molecular constants (Huber–Herzberg) | https://webbook.nist.gov/chemistry/ | web pages | planned (tables); meanwhile own data |
| **NIST CCCBDB** | rotational constants, moments of inertia, vibrational frequencies | https://cccbdb.nist.gov | web pages | planned; meanwhile own data |
| **ATcT** (Argonne) | enthalpies of formation (0 K, 298.15 K), molar masses | https://atct.anl.gov | **API** (https://atct.anl.gov/api/v1/) | **reads and downloads automatically**: `atct search`, `atct get`, recipes `atct:` |
| **IAEA CollisionDB / ALADDIN2** | cross-sections and rate coefficients of plasma collisions, with fit functions and DOIs | https://db-amdis.org/collisiondb/ | web download, **API** (JSON queries; Python package pycollisiondb) | planned |
| **NIFS databases** | atomic and molecular collision data (e.g. ionization of Xe) | https://dbshino.nifs.ac.jp | web (registration) | planned (sample needed) |
| **VAMDC** | portal to many atomic and molecular databases (e.g. BASECOL for rotational excitation) | https://portal.vamdc.eu | **API** (VAMDC-TAP, XSAMS) | not planned yet |
| **KIDA**, **UMIST (UDfA)** | gas-phase reaction rate coefficients (astrochemistry) | https://kida.astrochem-tools.org, https://umistdatabase.net | web download | not planned yet |
| **Quantemol-DB** | plasma chemistries and cross-sections | https://www.quantemoldb.com | commercial | – |
| **Papers** | tables, figures, fit formulas (e.g. Yoon 2008, Janev 2003, Phelps 1990) | journals, DOI | PDF | **reads**: `import --literature`, `extract` (tables, vector and scanned figures), formulas, review |
| **Own data** | values without a download source: PICLas parameters (VHS/VSS, InteractionID, characteristic temperatures), each with its reference (e.g. Bird 1994) | – | YAML file in the store | **reads**: `import`, recipes `own_data:` |

## Sources with an API

| Source | API | Authentication | piclas-db |
| --- | --- | --- | --- |
| ATcT | `https://atct.anl.gov/api/v1/` (species by ATcT ID, formula, name, …; JSON) | none needed for reading | automatic download in `build` and `fetch --need`, `atct search/get`; responses stored unchanged with TN version |
| LXCat 3 | REST API of LXCat 3 (JSON, JSON-Schema) | token, developer role | planned: token only from the environment (`$PICLAS_DB_LXCAT_TOKEN`), never in files |
| IAEA CollisionDB | `https://db-amdis.org/collisiondb/api/` (JSON queries by species, process, DOI) | none for reading | planned |
| VAMDC | VAMDC-TAP nodes (XSAMS) | none | not planned yet |

Automatic downloads follow the same rules as downloads by hand: the response is stored unchanged, with retrieval date, version of the
source and the person who added it, and every value in a database names it.

## Own data

Everything that comes from no download is kept as an own-data file **in the store**, not in recipes, so that all data are in one place:

```yaml
format: piclas-db own data
format_version: 1
name: piclas-parameters
description: PICLas parameters of species (VHS/VSS, InteractionID, characteristic temperatures)
species:
  Ar: {Tref: 273, dref: 4.17e-10, omega: 0.31, alphaVSS: 1.4, InteractionID: 1, Reference: "Bird 1994, Table A1"}
  N2: {Tref: 273, dref: 4.17e-10, omega: 0.24, alphaVSS: 1.36, InteractionID: 2, CharaTempVib: 3393.3, CharaTempRot: 2.87,
       Reference: "Bird 1994; Huber and Herzberg 1979"}
```

```bash
piclas-db import piclas-parameters.yaml      # into the store (and the private repository)
```

```yaml
# recipe
own_data: own/piclas-parameters
species:
  Ar: {}
  N2: {atct: 7727-37-9*0}       # heat of formation and mass from ATcT, the rest from the own data
```

Every species needs a `Reference`. Changing a value means importing a new version of the file (the old one stays in the store, recipes
use the newest, or a pinned one: `own/piclas-parameters@<sha256>`)). An existing database gives a first own-data file with
`piclas-db export SpeciesDatabase.h5 --own-data piclas-parameters.yaml` ([details](migrate.md)). Values written directly in a recipe still work (for tests), but
`build` notes them: they belong into the own data. Precedence: recipe, own data, ATcT.
