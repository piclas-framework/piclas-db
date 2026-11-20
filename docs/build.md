# Building a database

```bash
piclas-db build recipes/gec-argon.yaml -o database.h5
```

`build` reads a **recipe**, locates the original files (local store, then private repository, see [store.md](store.md)), parses
them, writes the database in the current layout ([layout.md](layout.md)) and checks the result ([checks.md](checks.md)). If an
original file is missing, `build` lists it and stops; download it and run `piclas-db import`.

Options: `--store`, `--offline` (do not update from the private repository), `--force` (overwrite the output).

## Recipes

A recipe is a YAML file that selects data from original files. It contains no third-party data, so recipes can be published,
e.g. in `recipes/` of this repository.

```yaml
description: Argon for the GEC reference cell
cross_sections:
  - source: lxcat/biagi-v7.1+phelps/ar     # <provider>/<dataset>[@sha256] in the store
    database: Biagi                        # LXCat database in the file (start of its name), needed if several have the species
    species: e / Ar                        # LXCat SPECIES
  - source: lxcat/biagi-v7.1+phelps/ar
    database: Phelps
    species: Ar^+ / Ar
    types: {Isotropic: ELASTIC}            # optional: LXCat type -> PICLas group
    processes: [Backscat, Isotropic]       # optional: only processes whose PROCESS contains one of these
    pair: Ar-ArIon1                        # optional: name of the collision pair
levels:
  - source: nist-asd/levels/ar
    species: Ar                            # PICLas species name
species:                                   # own data, written as attributes of /Species/<name>
  Ar: {MassIC: 6.6335e-26, InteractionID: 1}
reactions:                                 # own data, written as /Reactions/<name>
  'Ar+electron_ArIon1+electron+electron#1': {Reactants: [Ar, electron], Products: [ArIon1, electron, electron], ReactionModel: XSec, ChemistryModel: [[Ar_Ionization, '']]}
```

`@sha256` (or a prefix of it) pins the exact original file; without it the newest file of the dataset is used.

### Derived attributes: `masses` and `charges`

```yaml
masses: composition      # default: record (MassIC as given by own data or ATcT)
charges: name            # default: data (ChargeIC as given by own data)
```

`masses: composition` sets `MassIC` of every molecule and ion to the sum of its atoms (the neutral atom species of the database,
e.g. `C`, `O` from ATcT) minus charge × electron mass (species `electron`, else CODATA 2022). Every reaction then conserves mass
exactly; ATcT masses alone do not, since ATcT gives them to about four decimals in u (`SpeciesDatabase.h5`: XeIon1 is Xe minus 0.911
electron masses). Atoms keep their record masses; elements without an atom species (e.g. no `Fe` for `FeO`) are noted and the
species keeps its mass. The reference says `MassIC: by composition, C + 2 O` and no longer names ATcT for the mass.
`charges: name` sets `ChargeIC` to the charge in the name (`ArIon1`: 1, `electron`: −1) × 1.602176634e-19 C (exact since 2019).
Values written in the recipe take precedence. Applied to the species of `SpeciesDatabase.h5`, the two options remove all
`reaction-mass` and `species-ion-mass` warnings.

## From LXCat to PICLas

| LXCat | PICLas |
| --- | --- |
| ELASTIC, EFFECTIVE | `ELASTIC`, `EFFECTIVE` of the pair |
| EXCITATION naming a rotational state (`rot`, `J=`) | `ROTATION/<threshold>` |
| EXCITATION naming a vibrational state (`v=`, `vib`) | `VIBRATION/<threshold>` |
| other EXCITATION | `ELECTRONIC/<threshold>` |
| IONIZATION | `REACTION/<products>`, PICLas names, heavy species first, electrons last, e.g. `ArIon1-electron-electron` |
| ion-neutral `Backscat`, `Isotropic` | `BACKSCATTER`, `ELASTIC` |
| ATTACHMENT | skipped with a note (no PICLas cross-section chemistry for attachment) |

Thresholds come from `PARAM.` (`E = 11.55 eV`). Species names are converted to PICLas notation (`E` → `electron`, `Ar+` and `Ar^+` →
`ArIon1`, `Ar++` → `ArIon2`, excited states without the excitation). Collision pairs are named `<target>-<projectile>`, e.g.
`Ar-electron`, `Ar-ArIon1`; PICLas finds both orders.

Every cross-section gets the LXCat recommended reference of its database (`Reference`), the LXCat header of the process (`Info`),
its threshold (`Threshold [eV]`) and the original file with its sha256 (`* Source`). NIST ASD levels are converted to K with the
exact constants (hc/k_B = 1.438776877 cm K, 1 eV = 11604.51812 K) and sorted.

NIST ASD levels follow the PICLas convention of `SpeciesDatabase.h5` (from the former `maintain_database.py`): the bound levels,
then the ionization limit of the file (the first `Limit` row, e.g. `Ar II (3p5 2P*<3/2>) | Limit | 127109.842`) as last level with
degeneracy 1. PICLas takes the last level as ionization energy (QK ionization; heat of formation of the ion), and `check` reports a
last level that is not the limit (`levels-ionization-limit`). Levels at or above the limit (autoionizing) are left out, levels with
relative (`+x`) or doubtful (`?`) energies too. Energies in brackets (theoretical or derived) stay in the store (the original
file) but are left out of the database unless the level selection says `estimated: true`; `build` warns when most bound levels are
theoretical (He I, H-like ions: NIST ASD gives accurate calculated values for them). Both formats
of the levels form, "CSV (text)" and "ASCII (text)", give the same levels. For Ar I (current ASD), `build` reports:

```
  added  /Species/Ar/ElectronicLevel (423 levels, the last one the ionization limit, converted from cm-1 to K)
  note   Ar (nist-asd/levels/ar/2026-11-19_96e5938d.csv): 4 levels with energies in brackets (theoretical or derived) left out (estimated: true keeps them)
  note   Ar (nist-asd/levels/ar/2026-11-19_96e5938d.csv): 77 levels at or above the ionization limit (127109.842 cm-1) left out
```

and `diff` against `SpeciesDatabase.h5`: `421 levels in A, 423 in B; energies scaled by 1.0000324`. The old file holds the bound
levels of an older ASD version (one level less) converted with 1.43873021 K per cm⁻¹ instead of 1.438776877, and lacks the limit
level for Ar (the only atom without it).

Missing NIST levels are downloaded automatically by `build` and `fetch` (not with `--offline`): the levels form is called as a URL
(`https://physics.nist.gov/cgi-bin/ASD/energy1.pl`, spectrum from the dataset, `levels/arion1` → `Ar II`, whole table as CSV in
cm⁻¹), and the response is stored like a manual download (`NIST-Ar-II.csv`, retrieved today, by `user.name`).

## Example: GEC reference cell

Built from the LXCat download in the store, `recipes/gec-argon.yaml` reproduces the GEC tutorial file
`LXCat_Database_Biagi71_Argon_electron_Phelps_Ar_ArIon.h5`: the 5 electron cross-sections are identical, the two Ar⁺/Ar
cross-sections differ by up to 0.43 % because the tutorial file holds a copy rounded to 3 digits. `piclas-db check` finds no
errors or warnings in the built file.
