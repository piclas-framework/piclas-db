# T3 Adding data

How original data get into the store. Prerequisite: [T1](T1-getting-started.md) steps 1 and 2 (installation, identity).

## The rule: originals only

The store keeps the files exactly as downloaded (byte for byte), each with a `meta.yaml`: provider, dataset, species, retrieval date,
sha256, who imported it and with which piclas-db version. Databases are always built from these originals, never from copies, so
every value in a `database.h5` can be traced to its source.

## Who you are

```bash
piclas-db config --set user.name "Ada Lovelace"
piclas-db config --set user.email ada@example.org
```

This name is stored as `imported_by` with every import, as `created.by` in extraction records and as reviewer of reviews. In a store
that is a clone of the private repository (T4), it is also the author of the commits. Instead of the configuration file,
`$PICLAS_DB_USER_NAME` and `$PICLAS_DB_USER_EMAIL` can be set (e.g. in scripts or CI).

## Downloads with instructions

```bash
piclas-db guide lxcat/phelps/n2               # LXCat: database(s)/species
piclas-db guide nist-asd/levels/arion1        # NIST ASD: energy levels of Ar II
piclas-db guide --recipe recipes/gec-argon.yaml   # everything a recipe needs that is not in the store yet
```

Every guide also states the terms of the provider (LXCat and NIST data must not be redistributed).

## Import

```bash
piclas-db import --source-dir ~/Downloads                  # all recognized files; others are skipped
piclas-db import Ar_II_levels.csv --species ArIon1         # NIST levels without the spectrum in file name or content
piclas-db import own-data.csv --custom my-measurement --retrieved 2026-11-01   # anything else, under custom/
piclas-db import --source-dir ~/Downloads --dry-run        # only show what would happen
```

| File | Recognized by | Stored as |
|---|---|---|
| LXCat cross-sections (text) | `DATABASE:` and `SPECIES:`/`PROCESS:` lines | `lxcat/<databases>/<species>/` |
| LXCat swarm data | `DATABASE:` and `E/N` | `lxcat/<databases>/swarm/` |
| NIST ASD levels (CSV, tab, text) | columns `J` and `Level (cm-1, eV, Ry)` | `nist-asd/levels/<species>/` |
| Papers (PDF) | `--literature KEY --doi ...` | `literature/<key>/` |
| Anything else | `--custom NAME` | `custom/<name>/` |

A file that is already in the store (same sha256) is not imported again. A new download of the same dataset is stored next to the
old one; recipes use the newest, or a pinned one (`source: lxcat/phelps/n2@<sha256 prefix>`).

## Look at the store

```bash
piclas-db store              # list
piclas-db store --verify     # every file still matches its sha256?
```

## Papers

```bash
piclas-db import Yoon2008.pdf --literature yoon-2008 --doi 10.1063/1.2838023 \
    --reference "J.-S. Yoon et al., J. Phys. Chem. Ref. Data 37, 913 (2008)"
piclas-db extract yoon-2008 --page 15 --table 13 -o work/
piclas-db literature add work/table13-c1.extraction.yaml
piclas-db literature review yoon-2008/table13-c1 --approve        # reviewer: you
```

Details: [literature.md](../literature.md), [extract.md](../extract.md).
