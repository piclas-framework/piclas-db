# T2 Checking and comparing existing databases

What is in a database file, what is wrong with it, how two files differ, and where the data come from. No downloads needed: the
examples use files of the PICLas repository. About 20 minutes.

Prerequisite: [T1](T1-getting-started.md) step 1 (installation).

## 1. Check a database

```bash
piclas-db check SpeciesDatabase.h5
```

```
File:   SpeciesDatabase.h5
Layout: species database (SpeciesDatabase.h5 layout)
  species                44
  electronic level sets  38
  reactions              130
  collision pairs        11
  cross-sections         82
  diffusion sets         4
  surface entries        1

ERROR   /Species/ArIon1/ElectronicLevel: ground state degeneracy 1 instead of 4 (NIST ASD) [levels-ground-state]
ERROR   /Species/Fe: attribute 'alpha' is not read by PICLas (did you mean 'alphaVSS'?) [species-attribute-unknown]
ERROR   /Species/FeIon1: attribute 'alpha' is not read by PICLas (did you mean 'alphaVSS'?) [species-attribute-unknown]
WARNING /Cross-Sections/Ar-electron: 2 of 3 cross-sections stored as float32 [data-float32]
...
WARNING /Cross-Sections/Xe-electron/REACTION/XeIon2-electron-electron-electron: product(s) XeIon2 not in /Species: the reaction cannot be used [xsec-products-missing]
...
3 error(s), 35 warning(s), 77 info (show with --info)
```

Every line names the place in the file, the problem and, in brackets, the rule. What the rules check and why:
[checks.md](../checks.md). The levels:

| Level | Meaning | Examples above |
| --- | --- | --- |
| ERROR | PICLas gives wrong results or ignores data | VSS exponent never read (`alpha`), wrong degeneracy of the Ar⁺ ground state |
| WARNING | inconsistent or risky | float32 data, reactions whose products are not species, missing threshold region |
| INFO | worth knowing (`--info`) | sources, conventions |

`check` exits with code 1 if there are errors, so it can be used in scripts and CI.

## 2. Old file layouts

`check` reads every layout PICLas has used, e.g. an old cross-section file:

```bash
piclas-db check XSec_Database_O2_O.h5
```

```
File:   XSec_Database_O2_O.h5
Layout: legacy cross-section database (XSec_Database_*.h5)
  collision pairs        2
  cross-sections         26

ERROR   /O-electron/ELECTRONIIC: 'ELECTRONIIC' (9 datasets) is ignored by PICLas (did you mean 'ELECTRONIC'?) [xsec-name-unknown]
ERROR   /O2-electron/REACTION: O-electron-O and electron-O-O have the same products; only the order distinguishes the channels [xsec-reaction-ambiguous]
WARNING /O-electron/ELECTRONIIC: datasets 14, 14.0 have the same threshold 14 eV [xsec-threshold-duplicate]
...
```

A typo in a group name (`ELECTRONIIC`) means PICLas silently ignores nine excitation cross-sections of oxygen.

## 3. Repair: `migrate --fix`

```bash
piclas-db migrate XSec_Database_O2_O.h5 -o O2_O_fixed.h5 --fix
```

```
  Normalized: 5 empty group(s) dropped
  Normalized: cross-section metadata written as 'Type', 'Threshold [eV]', 'Reference', 'Info'
  Fixed:      O-electron: group ELECTRONIIC renamed to ELECTRONIC (9 dataset(s) now read by PICLas)
Check of O2_O_fixed.h5: 1 error(s), 12 warning(s) (details: piclas-db check O2_O_fixed.h5)
```

`migrate` writes the current layout; `--fix` repairs only what is unambiguous (typos in names, `alpha` → `alphaVSS`, unsorted
levels). What remains (here the two O₂ channels that differ only in the order of their products) needs a decision; `migrate` does
not guess.

## 4. Compare two files

```bash
piclas-db diff XSec_Database_Xe_Plasma-Biagi7-1.h5 SpeciesDatabase.h5
```

```
A: XSec_Database_Xe_Plasma-Biagi7-1.h5 (legacy cross-section database (XSec_Database_*.h5))
B: SpeciesDatabase.h5 (species database (SpeciesDatabase.h5 layout))

numerically different  /Cross-Sections/Xe-electron/ELASTIC: max deviation -31.27% at 75 eV, median -5.07%, ... [different source]
only in A              /Cross-Sections/Xe-electron/ELECTRONIC/11.7: ELECTRONIC cross-section only in A
...
numerically different  /Cross-Sections/Xe-electron/REACTION/XeIon1-electron-electron: max deviation -38.98% at 15 eV, median -23.72%, ...
renamed                /Cross-Sections/Xe-electron/REACTION/XeIon1-electron-electron: stored as .../electron-electron-XeIon1 in A
...
0 identical, 2 numerically different, 4 only in A, 11 only in B, 1 renamed
```

`diff` matches datasets across layouts and naming conventions (`electron-electron-XeIon1` = `XeIon1-electron-electron`),
compares on the common energy range even if the grids differ, and says by how much and where the data differ. `[different source]`
means the provenance differs (Biagi vs. Hayashi/NIFS): the two Xe databases are not two versions of the same data.

## 5. Look at the differences

```bash
piclas-db plot XSec_Database_Xe_Plasma-Biagi7-1.h5 SpeciesDatabase.h5 --pair Xe-electron --kind ELASTIC --compare -o xe-elastic.png
piclas-db plot SpeciesDatabase.h5 --pair Ar-electron --rate -o ar-rates.png        # Maxwellian rate coefficients k(T)
piclas-db plot SpeciesDatabase.h5 --species ArIon1 -o arion1-levels.png             # electronic levels
piclas-db plot SpeciesDatabase.h5 --list                                            # what can be plotted
```

`--compare` adds a panel with the deviation of every file from the first, in percent.

## 6. Text tables

```bash
piclas-db export SpeciesDatabase.h5 -o tables
```

```
SpeciesDatabase.h5 -> tables: 44 species, 38 electronic level sets, 130 reactions, 11 collision pairs, 82 cross-sections, ...
Convert back with: piclas-db migrate tables -o <file>.h5
```

The tables (YAML + CSV, 17 significant digits) can be read, edited and compared with git. `piclas-db migrate tables -o file.h5`
gives the `.h5` file back, and the round trip is exact.

## 7. Where do the data come from?

With a store that contains original downloads and extractions from papers (T1, T3), every cross-section can be traced to its
source, by comparing the numbers:

```bash
piclas-db rebuild SpeciesDatabase.h5 --explain --report sources.md --recipe-out draft.yaml
```

```
/Cross-Sections/Ar-electron/EFFECTIVE: partial (76 points)
    0-10000 eV    66 points  lxcat Phelps e / Ar: E + Ar -> E + Ar, Effective
    not explained: 10 point(s), 20000 eV, 30000 eV, 40000 eV, 45000 eV ...
/Cross-Sections/H2-H2Ion1/REACTION/H2Ion1-H2: complete (55 points)
    0.001-1000 eV    55 points  literature/janev-2003/h2plus-h2-cx-207  ** over the laboratory energy **
/Cross-Sections/H2-electron/REACTION/H2Ion1-electron-electron: combined (59 points)
    16-25 eV    19 points  literature/yoon-2008/table12-c1
    30-1000 eV    39 points  literature/yoon-2008/table13-c1
    sigma = 0 at 15.4 eV
...
82 cross-sections: 4 complete, 1 combined, 3 partial, 74 without source in the store; 2 over the laboratory energy
```

* **partial:** the Ar data are LXCat Phelps up to 10 keV and were extended to 100 keV by hand.
* **over the laboratory energy:** the H₂⁺ + H₂ charge-transfer data follow Janev's formula over the ion's laboratory energy, while
  PICLas uses the collision energy, which is half of it for H₂⁺ + H₂.
* **combined:** two tables of one paper, each in its own energy range (`plot --parts` / `--explain` show it).

Details: [rebuild.md](../rebuild.md).

## Summary

| Question | Command |
| --- | --- |
| What is in the file and what is wrong? | `check` |
| Can it be repaired? | `migrate --fix` |
| How do two files differ? | `diff`, `plot --compare` |
| Text instead of HDF5? | `export`, `migrate tables` |
| Where do the numbers come from? | `rebuild --explain` |
