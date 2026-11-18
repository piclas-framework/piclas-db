# T1 Getting started

From installation to a `database.h5` built from the original LXCat data and used in PICLas. About 20 minutes.

What you need: Python ≥ 3.11, git, a PICLas installation or clone (for its `SpeciesDatabase.h5` and the GEC tutorial), a web browser
for one download from LXCat.

## 1. Install

piclas-db is installed from its repository (it is not on PyPI):

```bash
git clone https://github.com/piclas-framework/piclas-db.git
cd piclas-db
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[extract]"      # [extract]: reading data from papers (pdfplumber, scikit-image)
piclas-db --version
```

Optional: Tesseract (`sudo apt install tesseract-ocr`) for scanned papers. Not needed for this tutorial.

## 2. Tell piclas-db who you are

Like git, piclas-db records who adds data (every import, extraction and review). Set it once:

```bash
piclas-db config --set user.name "Ada Lovelace"
piclas-db config --set user.email ada@example.org
piclas-db config --set store ~/piclas-db-store      # where the original files are kept (default: ~/.local/share/piclas-db/store)
piclas-db config
```

```
Configuration file: /home/ada/.config/piclas-db/config.yaml
  user:   Ada Lovelace <ada@example.org>
  store:  /home/ada/piclas-db-store  [configuration]
  mirror: not set (the remote of the store clone is used, if any)
```

Without name and email, `import`, `extract` and `literature add/review` stop with instructions. More settings:
[configuration.md](../configuration.md).

## 3. Check an existing database

Any database file can be checked, in any layout (`SpeciesDatabase.h5`, old `XSec_Database_*.h5`, electronic-state files):

```bash
piclas-db check <piclas>/SpeciesDatabase.h5
```

```
File:   .../SpeciesDatabase.h5
Layout: species database (SpeciesDatabase.h5 layout)
  species                44
  electronic level sets  38
  reactions              130
  collision pairs        11
  cross-sections         82
  ...
```

followed by errors, warnings and information (rules: [checks.md](../checks.md)). Tutorial T2 explains them.

## 4. Download the argon cross-sections from LXCat

The GEC reference cell tutorial of PICLas uses the Biagi-v7.1 (electrons) and Phelps (Ar⁺ in Ar) data. piclas-db tells you how
to download them:

```bash
piclas-db guide lxcat/biagi-v7.1+phelps/ar
```

```
lxcat/biagi-v7.1+phelps/ar (LXCat (www.lxcat.net))
  1. Open https://www.lxcat.net and go to the data center for scattering cross sections (https://fr.lxcat.net/data/set_type.php).
  2. Select "Scattering Cross Sections" and press "Next".
  3. Deselect all databases (minus button), then select: Biagi-v7.1, Phelps. Press "Next".
  4. Select the species: Ar. Press "Next".
  5. Keep all processes selected (or select the ones you need) and press "Next".
  6. Download the data in text format ("Download data"), save the file e.g. in ~/Downloads.
  ...
```

Follow the steps and save the text file in `~/Downloads`.

## 5. Import the download into the store

```bash
piclas-db import --source-dir ~/Downloads
```

```
Store: /home/ada/piclas-db-store
  imported .../lxcat-ar.txt -> lxcat/biagi-v7.1+phelps/ar/2026-06-01_95a5d06a.txt (lxcat cross-sections: biagi-v7.1+phelps/ar)
1 imported, 0 already in the store, 0 skipped, 0 failed
```

piclas-db recognizes the file by its content, checks every table, and keeps it unchanged in the store with its sha256, the
retrieval date and your name (`piclas-db store` lists the store). Other files in `~/Downloads` are skipped.

## 6. Build the database

A **recipe** says which data go into the database. The repository has one for the GEC tutorial:

```bash
cat recipes/gec-argon.yaml
piclas-db build recipes/gec-argon.yaml -o gec-argon.h5
```

```
  local store          lxcat/biagi-v7.1+phelps/ar: lxcat/biagi-v7.1+phelps/ar/2026-06-01_95a5d06a.txt
  added  /Cross-Sections/Ar-electron/ELASTIC
  added  /Cross-Sections/Ar-electron/ELECTRONIC/11.55
  added  /Cross-Sections/Ar-electron/ELECTRONIC/13.0
  added  /Cross-Sections/Ar-electron/ELECTRONIC/14.0
  added  /Cross-Sections/Ar-electron/REACTION/ArIon1-electron-electron
  added  /Cross-Sections/Ar-ArIon1/BACKSCATTER
  added  /Cross-Sections/Ar-ArIon1/ELASTIC
gec-argon.h5: 7 entries; check: 0 error(s), 0 warning(s)
```

The file says how it was made (`piclas-db check gec-argon.h5` shows it): piclas-db version, recipe, and every original file with
its sha256. Compared with the file of the GEC tutorial, the electron data are identical; the Ar⁺/Ar data differ by up to 0.4 %,
because the tutorial file contains a rounded copy:

```bash
piclas-db diff gec-argon.h5 <piclas>/tutorials/<gec>/LXCat_Database_Biagi71_Argon_electron_Phelps_Ar_ArIon.h5
```

```
5 identical, 2 numerically different
```

## 7. Look at the data

```bash
piclas-db plot gec-argon.h5 --pair Ar-electron -o ar-electron.png
piclas-db plot gec-argon.h5 --pair Ar-electron --rate -o ar-electron-rates.png     # Maxwellian rate coefficients k(T)
```

## 8. Use it in PICLas

PICLas reads cross-sections in two ways:

* **Cross-sections only**, species defined in `parameter.ini` (as in the GEC tutorial): build in the layout of
  `Particles-CollXSec-Database` and point PICLas to it:

  ```bash
  piclas-db build recipes/gec-argon.yaml -o gec-argon-xsec.h5 --layout xsec
  ```

  ```ini
  Particles-CollXSec-Database = gec-argon-xsec.h5
  ```

* **Complete species database** (species, reactions and cross-sections, like `SpeciesDatabase.h5`): `build` without `--layout`
  and `Particles-Species-Database = database.h5`. The recipe must then also contain the species (tutorial T5).

> **Check before the workshop:** step 8 has not been run with PICLas for this tutorial yet. The `xsec` layout is the one of the
> GEC tutorial file (`piclas-db check` and `diff` confirm it), so the GEC tutorial should run unchanged with `gec-argon-xsec.h5`.

## Next

* [T3 Adding data](T3-adding-data.md): more downloads, NIST levels, data from papers
* [T4 The private source repository](T4-private-repository.md): keep the store backed up and share it in the group
