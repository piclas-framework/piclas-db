# Data from papers

Many cross-sections exist only in papers (e.g. recommended values of a review, or fits). The `literature` provider stores the paper
as an original file and every dataset taken from it together with an **extraction record**: where the data comes from, how it was
obtained, with which version of piclas-db, how accurate it is and whether it has been reviewed. Only reviewed data are used by
`build`.

## Workflow

```bash
# 1. the paper (PDF) into the store
piclas-db import Yoon2008.pdf --literature yoon-2008 --doi 10.1063/1.2838023 \
    --reference "J.-S. Yoon et al., J. Phys. Chem. Ref. Data 37, 913 (2008)"

# 2. read the data automatically: tables, vector figures, scanned figures (see extract.md)
piclas-db extract yoon-2008 --page 15 --table 13 --by "Name" -o work/
#    -> work/table13-c1.csv + work/table13-c1.extraction.yaml (one per data column), filled in

# 3. store it: values and record are checked, the extraction is stored with review status "pending"
piclas-db literature add work/table13-c1.extraction.yaml

# 4. somebody compares the stored values with the paper and approves (or rejects) them
piclas-db literature review yoon-2008/table13-c1 --approve --reviewer "Name" --notes "39 rows checked"

piclas-db literature list
```

`extract` fills the CSV and the record ([extract.md](extract.md)). Only a few things are entered by hand: who extracted the data
(`--by`), what they are (`quantity.description` and the assignment in the record) and units that are not in the column header
(`--x-unit`, `--y-unit`).

**By hand** only where nothing can be read automatically: fit formulas (`literature template --formula`, see below) and data that
`extract` does not find (e.g. very small open symbols in a poor scan):

```bash
piclas-db literature template yoon-2008 ionization-h2plus --page "15 (927)" --table 13 -o work/
# enter the values exactly as printed in work/ionization-h2plus.csv, complete the record, then literature add as above
```

The values are stored as printed (e.g. in 10⁻¹⁷ cm²); the units in the record convert them to eV and m² when they are used. This
keeps the comparison with the paper simple and makes unit errors visible in the record instead of hiding them in the numbers.

## Extraction record

| Section | Content |
| --- | --- |
| `created` | UTC time, piclas-db version and commit, who entered or extracted the data |
| `source` | paper in the store (key, sha256 of the PDF), DOI, citation, page (index and printed label), table or figure |
| `method` | `manual` (typed), `text` (copied from the text layer), `ocr`, `vector` or `raster` (digitized figure) |
| `columns` | units of energy and cross-section as printed, e.g. `eV`, `keV`; `1e-16 cm^2`, `10^-17 cm2`, `A^2`, `a0^2`, `pi a0^2` |
| `quantity` | what the data are and the suggested assignment (pair, kind, key) |
| `accuracy` | accuracy of the extraction (exact for typed values) and the uncertainty stated in the paper, kept apart |
| `environment` | Python, numpy and platform; extraction tools add their versions |
| `review` | `pending`, `approved` or `rejected`, reviewer, date, notes |

`literature add` refuses data with energies that do not increase (typical typing error), negative values, unknown units, a missing
page or table/figure, and a paper that is not in the store or whose sha256 differs. A review changes only the record, never the
values; in a private-repository store it is committed like every import.

## Energy frame

PICLas looks cross-sections up at the **collision (center-of-mass) energy** E = μg²/2: this is what the reservoir regression checks
of PICLas confirm (`piclas-db reservoir --regressioncheck`, H₂⁺ + H₂ agree within 1 % only with the collision energy; with the
laboratory energy they would differ by about 40 %). Many papers on heavy-particle collisions give the laboratory (ion impact)
energy, so the record says which one is meant:

```yaml
columns:
  energy: {unit: eV, frame: lab, mass_amu: 2.0159, target_mass_amu: 2.0159}    # E_cm = E_lab m_target / (m_projectile + m_target)
```

`frame: collision` (default for energies) uses the values as they are; `frame: lab` (default for velocities) needs both masses and
converts. Electron collisions are unaffected (m_e ≪ m_target).

## Fit formulas

Review papers often give fit formulas instead of tables (e.g. Janev et al. 2003). A formula extraction stores the expression as
printed, evaluated on a logarithmic grid when it is used:

```bash
piclas-db literature template janev-2003 h2plus-h2-cid --page 85 --equation 209 --formula -o work/
```

```yaml
# work/h2plus-h2-cid.formula.yaml (E in the unit of the record, sigma in its cross-section unit)
expression: 4.05 / E**0.653 * exp(-3.15 / (E - 2.0)**1.65) + 0.139 * E**0.318 * exp(-680 / E**2.10) / (1 + 2.75e-12 * E**2.65 + 9.04e-23 * E**4.65)
parameters: {}        # named parameters, e.g. from a coefficient table
threshold: 2.0        # zero at and below
range: [2.0, 1.0e5]   # validity range from the paper
points: 200
```

Only arithmetic (`+ - * / **`, also `^`), `exp`, `log`, `log10`, `sqrt`, `abs`, numbers, `E` and the parameters are allowed; the
expression is parsed, never executed as code. `literature add` evaluates it and refuses values that are not finite or negative in
the range (threshold or range missing).

### Example: H₂⁺ + H₂ in SpeciesDatabase.h5

`SpeciesDatabase.h5` has `H2-H2Ion1/REACTION/H2Ion1-H2` and `H-H2-HIon1` from Janev et al. 2003, Eqs. (207) and (209). Evaluated
directly, both formulas reproduce the datasets exactly (ratio 1.000), but at the **laboratory** energy: the formulas use the ion
impact energy, while PICLas uses the collision energy, which is half of it for H₂⁺ + H₂. With `frame: lab`, the rebuilt datasets
differ from the database by +18 % (charge transfer) and −10 % (dissociation) in the median and up to a factor of two near the
thresholds: the database (and the regression checks built on the same data) evaluate these cross-sections at twice the intended
energy.

## Use in recipes

```yaml
literature:
  - source: literature/yoon-2008/ionization-h2plus   # [@sha256] pins one version
    pair: H2-electron
    kind: REACTION
    key: H2Ion1-electron-electron                     # products (REACTION) or threshold: <eV> (ELECTRONIC, VIBRATION, ROTATION)
```

`build` uses only approved extractions; `--allow-unreviewed` also accepts pending ones (never rejected ones), and `check` then
reports them (`literature-unreviewed`). Each dataset carries the citation with DOI, table and page (`Reference`), the description
(`Info`), the stored file with its sha256 (`* Source`), the extraction (`* Extraction`) and the review (`* Review`).

## Example: H2 ionization in SpeciesDatabase.h5

`SpeciesDatabase.h5` cites Yoon et al. 2008 for `H2-electron/REACTION/H2Ion1-electron-electron`. Entered from Table 13 (column H2⁺,
30–1000 eV), `piclas-db diff` finds the same cross-section on a different energy grid: the database dataset is Table 13 above
30 eV plus 20 points below 30 eV, which correspond to the total ionization of Table 12 (the paper states that dissociative ionization
is below 1 % there). Rebuilding it completely needs both parts; recipes that combine several extractions into one dataset follow.
