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

# 2. files for entering one table (or one column of a table)
piclas-db literature template yoon-2008 ionization-h2plus --page "15 (927)" --table 13 -o work/

# 3. enter the values exactly as printed in work/ionization-h2plus.csv, complete the record (units, who, what)
# 4. store it: values and record are checked, the extraction is stored with review status "pending"
piclas-db literature add work/ionization-h2plus.extraction.yaml

# 5. somebody compares the stored values with the paper and approves (or rejects) them
piclas-db literature review yoon-2008/ionization-h2plus --approve --reviewer "Name" --notes "39 rows checked"

piclas-db literature list
```

Data series of vector figures are read automatically with [`piclas-db extract`](extract.md), which writes the same files.

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
