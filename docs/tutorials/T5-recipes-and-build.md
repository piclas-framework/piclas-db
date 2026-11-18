# T5 Writing recipes and building a database

A **recipe** says which original data go into a `database.h5`. It contains no data itself, only references to files in the store
and the selection of processes, so it can be published, reviewed and versioned with git, while the data stay where their licences
allow them. About 30 minutes.

Prerequisites: [T1](T1-getting-started.md) (installation, identity, store) and the LXCat download of T1 step 4. The examples use the
ZIP that LXCat offers (TXT + XML, Biagi-v7.1 + Phelps, Ar); a TXT or XML file alone works the same way.

```bash
piclas-db import ~/Downloads/Download.zip
```

```
  imported .../Download.zip -> lxcat/biagi-v7.1+phelps/ar/2026-11-18_17861871.zip (lxcat cross-sections: biagi-v7.1+phelps/ar)
           10 new process(es), 0 with a newer or other update time, 0 already in the store
```

## 1. The first recipe

`argon.yaml`:

```yaml
description: Argon plasma - electrons (Biagi-v7.1) and Ar+ in Ar (Phelps)
cross_sections:
  - source: lxcat/biagi-v7.1+phelps/ar        # file in the store: <provider>/<dataset> (see piclas-db store)
    database: Biagi                            # LXCat database in the file (start of its name)
    species: e / Ar                            # LXCat SPECIES
  - source: lxcat/biagi-v7.1+phelps/ar
    database: Phelps
    species: Ar^+ / Ar
    processes: [Backscat, Isotropic]           # only these processes (parts of the LXCat PROCESS text)
    types: {Backscat: BACKSCATTER, Isotropic: ELASTIC}   # LXCat type -> PICLas group
```

```bash
piclas-db build argon.yaml -o argon.h5
```

```
  local store          lxcat/biagi-v7.1+phelps/ar: lxcat/biagi-v7.1+phelps/ar/2026-11-18_17861871.zip
  added  /Cross-Sections/Ar-electron/ELASTIC
  added  /Cross-Sections/Ar-electron/ELECTRONIC/11.55
  added  /Cross-Sections/Ar-electron/ELECTRONIC/13.0
  added  /Cross-Sections/Ar-electron/ELECTRONIC/14.0
  added  /Cross-Sections/Ar-electron/REACTION/ArIon1-electron-electron
  added  /Cross-Sections/Ar-ArIon1/BACKSCATTER
  added  /Cross-Sections/Ar-ArIon1/ELASTIC
```

What `build` does with every LXCat process:

| LXCat | PICLas |
| --- | --- |
| `ELASTIC`, `EFFECTIVE` | `/Cross-Sections/<pair>/ELASTIC`, `EFFECTIVE` |
| `EXCITATION` electronic / vibrational / rotational (from the process: `Ar*`, `v=1`, `J=0-2`) | group `ELECTRONIC`, `VIBRATION`, `ROTATION`, dataset named by the threshold (`11.55`) |
| `IONIZATION`, `ATTACHMENT` | `REACTION/<products>` (`ArIon1-electron-electron`) |
| ion–neutral (`Backscat`, `Isotropic`, …) | as mapped with `types` |
| collision pair | `<target>-<projectile>` in PICLas names (`Ar-electron`), or `pair:` |

## 2. Species and own data

A database for `Particles-Species-Database` also needs the species. Data that come from no download (masses, charges, PICLas
parameters) are given in the recipe, each species with its source:

```yaml
species:
  Ar:       {MassIC: 6.63352088e-26, ChargeIC: 0.0,             InteractionID: 1,  Reference: "CODATA 2018 / NIST atomic weights"}
  ArIon1:   {MassIC: 6.63260979e-26, ChargeIC: 1.60217653e-19,  InteractionID: 10, Reference: "Ar mass minus one electron mass"}
  electron: {MassIC: 9.1093826e-31,  ChargeIC: -1.60217653e-19, InteractionID: 4,  Reference: "CODATA"}
```

Without the species, `check` warns that the products of the ionization (`electron`, `ArIon1`) are not in `/Species`, and without
`Reference` that the species have no source. With both:

```
argon.h5: 10 entries; check: 0 error(s), 0 warning(s)
```

Heats of formation and masses can come from ATcT instead of being typed in: `CO: {atct: 630-08-0*0, InteractionID: 2}` downloads
the record and sets `HeatOfFormation_K` and `MassIC` ([atct.md](../atct.md); `piclas-db atct search carbon monoxide` finds the ID).

Attributes are written as they are: their names must be those PICLas reads (`check` knows them, e.g. `alphaVSS`, not `alpha`).
Reactions with own data (Arrhenius parameters) go into a `reactions:` section the same way.

## 3. Electronic levels from NIST ASD

```bash
piclas-db guide nist-asd/levels/ar              # download instructions (CSV, levels in cm-1)
piclas-db import ~/Downloads/Ar_I_levels.csv
```

```yaml
levels:
  - source: nist-asd/levels/ar
    species: Ar
  - source: nist-asd/levels/arion1
    species: ArIon1
```

The levels are converted to K with one constant (cm⁻¹ → K: 1.438776877), the degeneracy is 2J+1, and the ionization limit is not
taken as a level.

## 4. The built file says how it was made

```bash
piclas-db check argon.h5
```

```
File:   argon.h5
Layout: species database (SpeciesDatabase.h5 layout)
Made:   piclas-db 0.28.1 (commit ...), 2026-11-18T19:48:32+00:00: build argon.yaml
        1 original file(s); recipe embedded
```

The file contains the recipe, the piclas-db version, and every original file with its sha256 (attributes `* piclas-db ...`).
Every dataset names its source:

```
Reference:  Biagi-v7.1 database, www.lxcat.net, retrieved on November 18, 2026.
Info:       {'SPECIES': 'e / Ar', 'PROCESS': 'E + Ar -> E + E + Ar+, Ionization', 'PARAM.': 'E = 15.7 eV, complete set', ...}
* Source:   lxcat/biagi-v7.1+phelps/ar/2026-11-18_17861871.zip (sha256 17861871ec22...)
```

So the file can be rebuilt by anybody with access to the same originals:

```bash
piclas-db rebuild argon.h5 -o argon-again.h5
```

```
Rebuilt 10 entries from original files, copied 0 from the old file: argon-again.h5
Comparison with the old file: 10 identical
```

## 5. Which version of a download?

A new download of the same data is stored next to the old one; recipes use the **newest**. To keep a database reproducible
regardless of later downloads, pin the file with the start of its sha256 (`piclas-db store` shows it in the file name):

```yaml
  - source: lxcat/biagi-v7.1+phelps/ar@17861871
```

## 6. Downloads that grow: `source: lxcat`

If the processes are spread over several downloads (Elastic and Excitation first, Ionization later), select by database and species
instead of by file:

```yaml
cross_sections:
  - source: lxcat                              # all LXCat downloads in the store
    database: Biagi
    species: e / Ar
    processes: [Elastic, Excitation, Ionization]   # with source: lxcat, these must all be found
```

```
  added  /Cross-Sections/Ar-electron/REACTION/ArIon1-electron-electron (from lxcat/biagi-v7.1+phelps/ar/2026-11-18_17861871.zip)
```

Every dataset names the download it came from. The rules for duplicates, updates and conflicts: [T3](T3-adding-data.md#downloads-that-grow).

## 7. Data from papers

Extractions from papers ([literature.md](../literature.md)) are used by `literature:` entries, one cross-section each:

```yaml
literature:
  - source: literature/yoon-2008/table11-c1     # one extraction
    pair: H2-electron
    kind: REACTION
    key: H-electron-H                           # products (REACTION) or threshold: <eV> (ELECTRONIC, VIBRATION, ROTATION)
  - parts:                                      # one cross-section from two tables, each in its energy range
      - {source: literature/yoon-2008/table12-c1, range: [16, 25]}
      - {source: literature/yoon-2008/table13-c1, range: [30, 1000]}
    zero_at: 15.4                               # sigma = 0 at the threshold
    pair: H2-electron
    kind: REACTION
    key: H2Ion1-electron-electron
```

Only reviewed extractions are used; `build --allow-unreviewed` also takes pending ones (and `check` then warns).
`build --plot-parts plots/` shows how combined datasets are put together.

## 8. Output layouts

| Layout | For PICLas parameter | Command |
| --- | --- | --- |
| species database (default): species, levels, reactions, cross-sections | `Particles-Species-Database` | `build recipe.yaml -o database.h5` |
| cross-sections only, pairs at the root | `Particles-CollXSec-Database` (species in `parameter.ini`) | `build recipe.yaml -o xsec.h5 --layout xsec` |

## 9. When something is missing

| Message | What to do |
| --- | --- |
| `manual download lxcat/phelps/n2: missing: piclas-db guide lxcat/phelps/n2, then piclas-db import` | the file is in neither the store nor the private repository: download it |
| `no data for 'e / Ar' in database 'Hayashi'` | the file has no such database or species: check `database:` and `species:` (`piclas-db plot <file> --list`) |
| `no process 'Charge transfer' for 'Ar^+ / Ar' in Phelps database: download it ...` | a process listed under `processes:` is not in the downloads |
| `... differs between downloads with the same update time ...; pin one with @sha256` | two downloads disagree: choose one |
| `extraction is pending (review it ...)` | review the extraction from the paper, or `--allow-unreviewed` for a test build |

## 10. Starting from an existing database

To write the recipe of an existing database (e.g. `SpeciesDatabase.h5`), let piclas-db find the sources:

```bash
piclas-db rebuild SpeciesDatabase.h5 --explain --recipe-out draft.yaml
```

The draft contains every dataset whose source is in the store, and a comment for every other one ([T2](T2-checking-and-comparing.md)
step 7, [rebuild.md](../rebuild.md)).

## Checklist for a recipe

* `description:` says what the database is for
* every `cross_sections` entry names `database` and `species`; `processes` where only some are wanted
* ion–neutral types mapped with `types`
* species with `MassIC`, `ChargeIC`, PICLas parameters and `Reference`
* levels from NIST ASD for every species with electronic excitation
* pinned sources (`@sha256`) for databases that must stay reproducible
* `piclas-db check` after the build: 0 errors, warnings understood

Recipe format in detail: [build.md](../build.md).
