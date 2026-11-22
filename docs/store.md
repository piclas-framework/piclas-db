# Local store and import

## Local store

The local store keeps the original files downloaded from the data providers, byte for byte. It is the only input for building a
database, and it is never published (see [Where the data comes from](../README.md#where-the-data-comes-from)).

```
<store>/index.yaml                                     list of all files (generated)
<store>/<provider>/<dataset>/<retrieved>_<sha8>.<ext>  original file, never modified or overwritten
<store>/<provider>/<dataset>/<retrieved>_<sha8>.<ext>.meta.yaml
```

Example: `lxcat/biagi-v7.1+phelps/ar/2026-06-01_95a5d06a.txt` for an LXCat download with the Biagi-v7.1 and Phelps data of argon.

The location is `--store`, otherwise `$PICLAS_DB_STORE`, otherwise `store` in the configuration file, otherwise
`$XDG_DATA_HOME/piclas-db/store` (`~/.local/share/piclas-db/store`).

A store that is set explicitly (`--store`, `$PICLAS_DB_STORE`, configuration) but does not exist, e.g. deleted, moved or on an
unmounted disk, is not treated as empty: commands that only read it (`store`, `build`, `rebuild`, `guide`, `plot`, `literature list`,
...) stop with instructions (restore it with `fetch --mirror`, create it with `mkdir -p`, or set another store). Commands that add data
(`import`, `extract`, `atct`, `literature add`/`want`) create it with a warning that it is a new, empty store, not connected to a
private repository; dry runs create nothing. The default location is created by the first import.

`meta.yaml` records the provider, kind, dataset, species, retrieval date and where it came from (file content or command line),
the original file name, sha256, size, import time and tool version, and the provider details: for LXCat the databases with their
permalinks, the recommended references and the collision processes per species and type; for NIST ASD the energy unit and the
number of levels.

`piclas-db store` lists the store, `piclas-db store --verify` checks every file against its sha256.

## `piclas-db import`

```bash
piclas-db import --source-dir ~/Downloads        # all recognized files in a directory, unknown files are skipped
piclas-db import lxcat_ar.txt Ar_II_levels.csv    # single files, unknown files are errors
```

Files are identified by their content, not by their name:

| Provider | Recognized by | Dataset | Retrieval date |
| --- | --- | --- | --- |
| LXCat cross-sections | `DATABASE:` and `SPECIES:`/`PROCESS:` lines | databases and target species, e.g. `biagi-v7.1+phelps/ar` | `Generated on` line |
| LXCat swarm data | `DATABASE:` and `E/N` | databases, `swarm` | `Generated on` line |
| NIST ASD levels | columns `J` and `Level (cm-1 \| eV \| Ry)` (CSV, tab or `\|` separated) | `levels/<species>` | `--retrieved` |
| own data | `--custom NAME` | `custom/<name>` | `--retrieved` |

LXCat files are parsed completely, including ion-neutral blocks without a type keyword (e.g. Phelps Ar⁺/Ar backscattering), and
rejected if a table cannot be read, has fewer than two points, decreasing energies or negative values. The species of a NIST ASD
file is taken from a spectrum name above the table (e.g. `Ar II` → `ArIon1`), from the file name (`Ar_I_levels.csv` → `Ar`) or
from `--species`. Files already in the store (same sha256) are not imported twice; a changed download of the same dataset is stored
next to the previous one.

Options: `--store`, `--species`, `--custom NAME`, `--retrieved YYYY-MM-DD`, `--dry-run`.

Parsers for NIFS, ATcT and the IAEA databases follow once example downloads are available; until then such files can be stored with
`--custom`.

## Private repository

The local store can be a clone of a private git repository of the organisation, which backs up the original files and shares them
between users. Access uses the user's own SSH key and repository permissions; piclas-db never handles credentials, and git runs
non-interactively, so missing access fails immediately with a hint instead of waiting for a password.

```bash
piclas-db fetch --mirror git@github.com:<org>/<private-repo>.git   # first time: clone (also works for an empty repository)
piclas-db import --source-dir ~/Downloads                          # every imported file is committed separately
piclas-db push                                                     # back up the commits
piclas-db fetch                                                    # later: update from the private repository
```

* The repository URL is taken from `--mirror`, `$PICLAS_DB_MIRROR` or the remote of an existing clone.
* An existing local store that is not yet a clone is adopted: the repository is cloned next to it, local files that are not in the
  repository are added in one commit, and the old store is kept as `<store>.backup-<date>`.
* Every import is one commit with the provenance in the message, e.g.
  `Add lxcat cross-sections biagi-v7.1+phelps/ar (retrieved 2026-06-01, sha256 95a5d06a)`. Since imports only add new files, `fetch`
  and `push` rebase local commits without conflicts. `index.yaml` is generated locally and never committed.
* `push` refuses to push if a file no longer matches its sha256 (`piclas-db store --verify`).
* Without access to the private repository, everything works with the local store and manual downloads.

## Locating the files a database needs

`piclas-db fetch --need PROVIDER/DATASET[@SHA] ...` looks for original files in this order and reports where each was found:

1. local store
2. private repository (updates the store once if something is missing locally)
3. automatic download (no provider supported yet; a candidate is the IAEA CollisionDB API)
4. manual download: step-by-step instructions with `piclas-db guide`, then `piclas-db import`

Example: `piclas-db fetch --need lxcat/biagi-v7.1+phelps/ar nist-asd/levels/ar@1a3ff74d`. The exit code is 1 if a manual
download is required. `build` and `rebuild` use the same lookup.
