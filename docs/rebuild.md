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

1. **Derive a recipe** from the provenance in the old file (written to `NEW.recipe.yaml`):
   * cross-sections with an LXCat recommended reference (`Biagi-v7.1 database, www.lxcat.net, ...`) and the LXCat header in `Info`
     (`SPECIES: e / Ar`); references stored on a group (e.g. `ELECTRONIC`) count for its datasets; cross-sections without reference
     get the database of other cross-sections of the same LXCat species in the pair; ion-neutral pairs without header
     (`Ar-ArIon1`) are `Ar^+ / Ar`
   * electronic levels with a NIST reference, or all levels with `--levels-from-nist`
   * if a matching file is in the store, the recipe pins it with its sha256
2. **Locate the original files**: local store, private repository; missing files are listed with the download guide, and
   rebuild stops (import them and run rebuild again).
3. **Build** the database from the recipe. Everything that cannot be rebuilt (no usable provenance), and species attributes,
   reactions, diffusion and surface data, is copied from the old file and listed as `copied (not rebuilt)`.
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
