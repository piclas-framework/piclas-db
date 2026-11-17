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

The location is `--store`, otherwise `$PICLAS_DB_STORE`, otherwise `$XDG_DATA_HOME/piclas-db/store`
(`~/.local/share/piclas-db/store`). Version 0.7.0 makes the store a clone of the private source repository.

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
