# Migrating and exporting databases

## `piclas-db migrate SOURCE -o OUTPUT.h5`

Converts a database of any layout (legacy XSec, legacy electronic state, current species database) or a directory with ASCII
tables into the current layout ([layout.md](layout.md)). The source file is never modified, and an existing output file is only
overwritten with `--force`.

**Always applied** (representation only, PICLas reads the same data, existing `parameter.ini` files keep working):

* legacy groups moved to `/Cross-Sections/<pair>` and `/Species/<name>/ElectronicLevel`
* all data as float64
* strings read by PICLas as fixed-length, null-padded ASCII with 255 characters (PICLas aborts on variable-length and
  null-terminated strings), logicals as integers
* metadata in one scheme: `Type`, `Threshold [eV]`, `Reference`, `Info` on cross-sections, `* Reference` on species and reactions
* empty groups dropped

**`--fix`** applies corrections that change what PICLas reads:

* group and attribute names with typos renamed, e.g. `ELECTRONIIC` → `ELECTRONIC` (the 9 electronic excitations of O in
  `XSec_Database_O2_O.h5` are then used) and `alpha` → `alphaVSS` (Fe, FeIon1 in `SpeciesDatabase.h5`)
* electronic levels sorted by energy

**`--canonical-products`** renames reaction cross-sections to the conventional product order (heavy species first, electrons
last), e.g. `electron-electron-XeIon1` → `XeIon1-electron-electron`. PICLas finds reaction cross-sections by the product order in
`parameter.ini`, which therefore has to be adapted.

Renames that would collide with an existing entry are skipped and reported, e.g. `O-electron-O` and `electron-O-O` in the O₂
files: both would become `O-O-electron`. Such channels need distinct names agreed with PICLas. Data errors that require the original
source (e.g. the ArIon1 ground-state degeneracy or hydrogen levels in cm⁻¹) are not corrected by `migrate`; they are fixed by
rebuilding from the source.

After writing, `migrate` checks the result and prints the number of errors and warnings (`piclas-db check OUTPUT.h5` shows them).

## `piclas-db export SOURCE -o DIRECTORY`

Writes a database of any layout as ASCII tables into a new or empty directory. The tables are input and output of the tool only and
are not stored in a repository.

```
database.yaml                              format version, layout of the source, file and group attributes
species.yaml                               species attributes and provenance
species/<name>.electronic_levels.csv       degeneracy, energy [K]
species/<name>.vibrational_levels.csv      energy [K]
reactions.yaml                             reaction attributes and provenance
cross_sections/<pair>/metadata.yaml        provenance, kind, key and threshold of every cross-section
cross_sections/<pair>/[<group>/]<key>.csv  energy [eV], cross-section [m^2]
diffusion/<pair>/<database>/               metadata.yaml and one CSV per quantity
surface.yaml, surface/<name>.csv           surface chemistry
```

Numbers are written with 17 significant digits. Converting the tables back with `piclas-db migrate DIRECTORY -o file.h5`
reproduces every value, attribute and data type of a migrated file exactly (round-trip test in `tests/test_migrate.py`).

## `piclas-db export SOURCE --own-data FILE`

Writes the species attributes of a database as an own-data file (YAML, [format](sources.md#own-data)) for the store, the first step of
rebuilding an existing file from sources: the values stay as they are, and every species gets a `Reference` that says where each value
comes from, as far as the file tells.

```bash
piclas-db export SpeciesDatabase.h5 --own-data piclas-parameters.yaml --origin "SpeciesDatabase.h5 (2026-10-09)"
```

```
SpeciesDatabase.h5 -> piclas-parameters.yaml: 44 species, origin "SpeciesDatabase.h5 (2026-10-09)"
  ATcT (35 species): HeatOfFormation_K, MassIC left out (use --keep-atct to keep them)
  source unknown: 332 values in 42 species (see the Reference of each species)
```

* The `Reference` of a species starts with the origin (`--origin`, default: file name and modification date), then the sources named
  per value (labels such as `HeatOfFormation`, `Moments of Inertia` or attribute names in tabular references), then the values without
  a named source (`source unknown: ...`). A reference without labels (e.g. a paper for the electron) is kept with the note which values
  it may stand for.
* Heats of formation and masses of species whose reference names ATcT are left out: a recipe takes them from ATcT (`atct: <ID>`),
  which documents version and record. `--keep-atct` keeps them (exact copy of the old values). `--atct-from RECIPE` also leaves
  them out for the species with an ATcT ID in the recipe (e.g. ions mapped by formula and charge, [masses from one source](atct.md)).
* Electronic and vibrational levels are not own data; they come from NIST ASD (recipe `levels`).
* Species names that YAML would read as something else are quoted (`'NO'`, YAML reads `NO` as false); recipes and own-data files with
  such unquoted names are rejected.

Check the file (replace `source unknown` where the source is found), then `piclas-db import piclas-parameters.yaml`. Round trip: with
`--keep-atct`, import and `build` with all species reproduce every species attribute of the old file, values and integer/float types
(`tests/test_own.py`).
