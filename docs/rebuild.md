# Download guide and rebuild

## `piclas-db guide`

Step-by-step instructions for downloading original files by hand:

```bash
piclas-db guide lxcat/biagi-v7.1+phelps/ar nist-asd/levels/arion1   # given files
piclas-db guide --recipe recipes/gec-argon.yaml                      # files of a recipe that are missing in the store
```

The instructions per provider are kept in `piclas_db/guides.yaml`, not in the code, because websites change; every download is
checked by `piclas-db import` anyway. Each guide also states the terms of the provider (e.g. no redistribution of LXCat data).

## `piclas-db rebuild OLD.h5 -o NEW.h5`

Rebuilds an existing database (any layout) from the original files and compares the result with the old file:

If the old file was built by piclas-db, its embedded recipe is used (see the provenance attributes in
[layout.md](layout.md#provenance-root-attributes)); `--derive` derives it from the data instead.

1. **Derive a recipe** from the provenance in the old file (written to `NEW.recipe.yaml`):
   * cross-sections with an LXCat recommended reference (`Biagi-v7.1 database, www.lxcat.net, ...`) and the LXCat header in `Info`
     (`SPECIES: e / Ar`); references stored on a group (e.g. `ELECTRONIC`) count for its datasets; cross-sections without reference
     get the database of other cross-sections of the same LXCat species in the pair; ion-neutral pairs without header
     (`Ar-ArIon1`) are `Ar^+ / Ar`
   * cross-sections with an LXCat header but without database name: identified by species, process and update time in the LXCat
     downloads of the store (the update time is unique per LXCat process); download candidates first, then rebuild again
   * electronic levels with a NIST reference, or all levels with `--levels-from-nist`
   * if a matching file is in the store, the recipe pins it with its sha256
2. **Locate the original files**: local store, private repository; missing files are listed with the download guide, and
   rebuild stops (import them and run rebuild again).
   * reactions: the rate table row with the same C, n and T_d (the table closest in C, preferably the paper of one of the
     reaction's chemistry models); reactions in no table keep their values as `arrhenius` with "source unknown"; QK reactions
     and the references of the chemistry models are taken over
3. **Build** the database from the recipe. Everything that cannot be rebuilt (no usable provenance), and species attributes,
   diffusion and surface data, is copied from the old file and listed as `copied (not rebuilt)`. `--allow-unreviewed` uses rate
   tables and extractions that are not reviewed yet.
4. **Compare** old and new file as `piclas-db diff` does.

The derived recipe can be edited (e.g. to add the provenance an old file is missing) and built again with `piclas-db build`.

## Results for existing files

| File | Rebuilt | Result |
| --- | --- | --- |
| GEC tutorial (`LXCat_Database_Biagi71_..._ArIon.h5`) | 5 electron cross-sections from the LXCat download; Ar⁺/Ar copied (no provenance) | 7 identical |
| GEC-reference-cell (`..._ArIon_1.h5`) | all 7 cross-sections | Ar⁺/Ar up to 0.43 %, ionization up to 6.4 % (rounded copies in the old file) |
| `XSec_Database_Xe_Plasma-Biagi7-1.h5` | needs the Biagi-v7.1 Xe download | guide for `lxcat/biagi-v7.1/xe` |
| `Electronic-State-Database.h5` | needs NIST ASD levels of Ar, Ar II, Ar III | guide for the three spectra |
| `XSec_Database_O2*.h5` | nothing: the references only name `xsec_collision.txt` | not reproducible; add the LXCat databases to the derived recipe |

## Where the data come from: `rebuild --explain`

```bash
piclas-db rebuild SpeciesDatabase.h5 --explain --report sources.md --recipe-out draft.yaml
```

Every cross-section of the file is compared **point by point** with everything in the store: the processes of all LXCat downloads,
all extractions from papers (tables, figures) and all fit formulas (evaluated at the energies of the dataset). A point is explained by
a source if energy and cross-section are the same to float32 precision; σ = 0 is not used as evidence (thresholds are in many
sources), and a source must explain at least three points (or all of its own). Sources of other species are not considered (LXCat
species, assignment of an extraction). Extractions over the laboratory energy are also tried over the laboratory energy.

| Status | Meaning |
| --- | --- |
| complete | all points from one source (apart from σ = 0 at the threshold) |
| combined | all points from several sources, each in an energy range |
| partial | some points from sources, others not (e.g. an extension to higher energies) |
| unknown | no point from the store (the download is missing) |

`--report` writes a Markdown table, `--recipe-out` a draft recipe for the complete and combined datasets (LXCat processes grouped by
pair, database and species with `source: lxcat`; papers with their parts and `zero_at`), with a comment for every dataset that is not
covered. Datasets that match their source only **over the laboratory energy** are marked: a rebuild over the collision energy will
differ, as PICLas expects the collision energy.

Example, `SpeciesDatabase.h5` against a store with the GEC LXCat downloads, Yoon et al. 2008 and Janev et al. 2003:

```
82 cross-sections: 4 complete, 1 combined, 3 partial, 74 without source in the store; 2 over the laboratory energy
/Cross-Sections/Ar-electron/EFFECTIVE: partial (76 points)
    0-10000 eV    66 points  lxcat Phelps e / Ar: E + Ar -> E + Ar, Effective
    not explained: 10 point(s), 20000 eV, 30000 eV, 40000 eV, 45000 eV ...
/Cross-Sections/H2-H2Ion1/REACTION/H2Ion1-H2: complete (55 points)
    0.001-1000 eV    55 points  literature/janev-2003/h2plus-h2-cx-207  ** over the laboratory energy **
/Cross-Sections/H2-electron/REACTION/H2Ion1-electron-electron: combined (59 points)
    16-25 eV    19 points  literature/yoon-2008/table12-c1
    30-1000 eV    39 points  literature/yoon-2008/table13-c1
    sigma = 0 at 15.4 eV
```

The 74 unknown datasets are the downloads still missing (LXCat Phelps for H₂, N₂, CO₂, He; Hayashi for Xe; NIFS; Phelps 1990):
with every download, the report shows what it covers.

### Reactions

With rate tables in the store ([literature.md](literature.md)), `rebuild --explain` also compares every Arrhenius reaction: per
chemistry model of the reaction and per third body of that model, whether the paper of the model has the same C (within 0.6 %;
the usual rounding of a converted prefactor to 3–5 digits is not reported), n and T_d, and which tables have the same values at all
(invented species and values):

```
Tx2+M_Tx+M+Tx#2                    C=3.32e-09 n=-1.500 T_d=59000
    differs   Air_7Spec_9Reac_Author2001: Tx2, Qq2: T_d 59000 vs. 59500 (row 2)
    match     Air_7Spec_12Reac_Other2010
    same values in: literature/other-2010/table4 row 7 (others)
```

Status per reaction and model: `match`, `differs`, `missing` (reaction or third body not in the table), `no table` (paper not
extracted yet).
