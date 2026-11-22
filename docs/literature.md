# Data from papers

Many cross-sections exist only in papers (e.g. recommended values of a review, or fits). The `literature` provider stores the paper
as an original file and every dataset taken from it together with an **extraction record**: where the data comes from, how it was
obtained, with which version of piclas-db, how accurate it is and whether it has been reviewed. Only reviewed data are used by
`build`.

## Workflow

```bash
# 1. the paper (PDF) into the store; DOI, citation and key (first author and year, here yoon-2008) are found automatically
#    (see "DOI and citation" below); --literature KEY chooses the key
piclas-db import 1_2838023.pdf --literature

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

## DOI and citation

`import --literature` finds the DOI and the citation itself; `--doi` and `--reference` are only needed where that fails or to
override it.

1. **DOI** from, in this order: the PDF metadata (document info, XMP), the text of the first two pages (journals print the
   article's own DOI there; the reference list comes later), the file name of the download (IOP `0953-4075_2F21_2F6_2F014`, APS
   `PhysRevA_6_1507`, AIAA `6_2007-4543` and `1_22095`, AIP `1_872535`, Academic Press `adnd_1997_0732`, URL-encoded DOIs).
2. **Check at Crossref**: a DOI is taken when Crossref knows it and its title is on the first pages of the PDF. This catches a
   download that contains another article than its name says (a wrong file from the publisher). Scans without text are not
   compared.
3. **Search**: without an accepted DOI, the first lines of the PDF (or the file name of a scan) are searched at Crossref; the best
   match is taken if its title is in the PDF.
4. **Citation** from the Crossref record: authors (initials), title, journal volume(issue):pages, year.

The import prints one block per paper with a mark (on a terminal in color: green ✓ fine, yellow ! to check, red ✗ failed,
= already in the store), the key, the DOI with where it was found and the link to check it, the citation and the reasons to check;
at the end a summary and the next steps as commands to copy (`--dry-run` first is a good idea for many papers):

```
✓ author-2001          2001-Author-Rate-Parameters.pdf
      DOI   10.9999/test.2001.42 (first pages)   https://doi.org/10.9999/test.2001.42
      cite  A. Author, B. J. Other, Rate parameters for imaginary plasmas, J. Invent. Res. 12(3):100-110, 2001 (Crossref)
! other-1994           1994-Other-Book.pdf
      DOI   10.9999/book (Crossref search)   https://doi.org/10.9999/book
      check DOI found by searching Crossref for the first lines of the PDF: open the link and compare title and authors
✗ —                    1995-Laux-Direkte-Simulation.pdf
      DOI and citation not found: give --doi or --reference

3 paper(s): 1 fine, 1 to check, 1 failed (dry run: nothing copied)

Next steps
1. Check the 1 paper(s) marked ! (open the DOI link, compare title, authors and key). A wrong DOI or key: import that file alone, e.g.
    piclas-db import 1994-Other-Book.pdf --literature other-1994 --doi DOI
2. Import the 1 failed paper(s) one by one, with the DOI or the citation (books, theses and reports have no DOI):
    piclas-db import 1995-Laux-Direkte-Simulation.pdf --literature laux-1995 --doi DOI   # or --reference "AUTHORS, TITLE, ..., YEAR"
3. Import the 2 paper(s) found (move the ones you import alone out of the way first):
    piclas-db import 2001-Author-Rate-Parameters.pdf \
        1994-Other-Book.pdf \
        --literature
```

A paper is marked ! when its DOI was found by a search or in the file name only, Crossref could not be asked, it has no DOI, its
key got a suffix (`park-1993b`: another paper has that key), or a note applies (e.g. the title is not on the first pages).

**Overview, checklist and review.** Each block is numbered (`[7/18]`) and separated by a line; after the last block a table lists
every paper in one line (number, mark, key, DOI with where it was found or the reason of a failure, file). `--checklist FILE` writes
the same as a Markdown checklist with the DOI links, to tick off in an editor.

`--review` goes one step further: after the overview it walks through the papers still to decide, one at a time, and keeps the position
itself:

```
[7/18] ! bird-1994            1994-Bird-Molecular-Gas-Dynamics-….pdf
      DOI   10.1093/… (Crossref search)   https://doi.org/10.1093/…
      check DOI found by searching Crossref for the first lines of the PDF: open the link and compare title and authors
  [2/9] o open, y import, k key, d doi, r citation, s skip, q quit >
```

`o` opens the DOI link in the browser, `y` imports the paper, `k KEY` changes the key, `d DOI` or `r TEXT` give the DOI or the citation
(looked up again), `s` skips, `q` stops. Skipped papers are remembered in `.piclas-db-review.yaml` of the current directory; the same
command later continues with the papers not decided yet (imported ones are `=`). `--review` needs a terminal.

While the papers are looked up at Crossref, a bar with counter and spinner shows the progress on the terminal
(`⠋ [█████░░░░░░░░░░░░░░░] 4/18  22% 1995-Laux-….pdf: DOI and citation (Crossref)`); it is drawn on stderr and disappears when
the output is redirected.

Colors: `--color auto` (default: on a terminal), `--color always` (also through a pipe, e.g. `| tee import.txt` or `| less -R`),
`--color never`; the environment variables `NO_COLOR` (no colors) and `FORCE_COLOR` or `CLICOLOR_FORCE` (colors also into a pipe)
work too. `--color` is also an option of `diff`.

Offline (or with `--no-lookup`) the DOI from the PDF, or from a file name that allows only one DOI, is taken unchecked, without
citation from Crossref. The paper's record keeps where the DOI and the citation came from (`doi_found_in`, `reference_from`).
Books and old papers without DOI need `--reference` and a key (`--literature KEY`).

**The same paper in another file:** a cover page added or removed by the journal, a watermark with the download date, or another
download give another sha256. A new PDF is therefore also compared with the papers in the store: by its DOI (reliable), and for
papers without DOI by the text of the first 8 pages (word sequences compared with tolerance; at least 70 % of the shorter text must
be in the other; scans without text layer cannot be compared). A match is marked `≈` and not imported:

```
≈ laux-1995            laux-cut.pdf
      same paper as laux-1995 (81% of the text of the first 8 pages), other file: 11 instead of 12 pages
      not imported; to keep this file as another version: --literature laux-1995 --new-version
```

`--new-version` keeps the file as a further version under the paper's key (its own sha256; extraction records name the exact file,
so page numbers stay valid). A suffixed key (`park-1993b`) is only given to a different paper of the same first author and year.

**Key and file name:** `--literature` without a key takes the first author's family name and the year from Crossref (`gokcen-2007`,
letters without accents), with `b`, `c`, ... if the key is taken. The paper is stored as `literature/<key>/<key>_<sha256[:8]>.pdf`
(papers imported before 0.44.0 keep their names `undated_<sha>.pdf`).

## Wanted papers

Papers that are needed but not yet in the store go on a wanted list, `literature/wanted.yaml` in the private store (it shows
which papers the store holds and lacks, so it is not part of the public repository):

```bash
piclas-db literature want author-1990 --reference "A. Author, A Book, Publisher, 1990" --needed-for "rate table p. 326"
piclas-db literature want other-1987 --reference "B. Other, J. Test 20:1, 1987" --doi 10.0000/other --note "publisher gave the wrong file"
piclas-db literature wanted        # the list, with doi.org links, what each paper is needed for and the notes
piclas-db literature unwant author-1990
```

`want` on an existing key updates the entry and adds the note. `piclas-db store` ends with `2 paper(s) wanted: …`. Importing a paper
whose key or DOI matches an entry removes it (`WANTED other-1987: no longer wanted`). In a store that is a git repository, every
change of the list is committed.

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

### Parameters from a table

Many review papers give one formula and a table of parameters, one column per process (Janev et al. 2003: Eq. (14) and Table 3 for
ionization from 1s, 2s, 2p, n = 2, 3). `extract --table` stores such a table as a **parameter table** (no energy column, first column:
row labels), and a formula takes its parameters from one column:

```bash
piclas-db extract janev-2003 --page 130 --table 3 -o work/            # -> work/table3.extraction.yaml (parameter table)
piclas-db literature add work/table3.extraction.yaml
piclas-db literature template janev-2003 h-ion-1s --page 13 --equation 14 --formula --parameters-from janev-2003/table3 --column 1s -o work/
```

```yaml
# work/h-ion-1s.formula.yaml
expression: 1e-13 / (I * E) * (A0 * log(E / I) + A1 * (1 - I / E) + A2 * (1 - I / E)**2 + A3 * (1 - I / E)**3 + A4 * (1 - I / E)**4 + A5 * (1 - I / E)**5)
parameters_from:
  table: janev-2003/table3
  column: 1s                  # header text or number (1 = first value column)
  rows: {I: In (eV)}          # only where parameter name and row label differ (compared without spaces and case)
threshold: 13.6
range: [13.6, 1.0e5]
```

`literature add` reads the parameters from the stored table (every parameter of the expression must be found, otherwise the rows of
the table are listed) and freezes them into the record together with the sha256 of the table. One formula per column: for the
other states only `column` changes. Janev Eq. (14) with Table 3, 1s: maximum 6.2 × 10⁻¹⁷ cm² at 57 eV.

### Example: H₂⁺ + H₂ in SpeciesDatabase.h5

`SpeciesDatabase.h5` has `H2-H2Ion1/REACTION/H2Ion1-H2` and `H-H2-HIon1` from Janev et al. 2003, Eqs. (207) and (209). Evaluated
directly, both formulas reproduce the datasets exactly (ratio 1.000), but at the **laboratory** energy: the formulas use the ion
impact energy, while PICLas uses the collision energy, which is half of it for H₂⁺ + H₂. With `frame: lab`, the rebuilt datasets
differ from the database by +18 % (charge transfer) and −10 % (dissociation) in the median and up to a factor of two near the
thresholds: the database (and the regression checks built on the same data) evaluate these cross-sections at twice the intended
energy.

## Combining extractions

One cross-section can be put together from several extractions, each used in an energy range (collision energy in eV):

```yaml
literature:
  - parts:
      - {source: literature/yoon-2008/table12-c1, range: [16, 25]}     # total ionization (dissociative part < 1 % there)
      - {source: literature/yoon-2008/table13-c1, range: [30, 1000]}   # partial ionization H2+
    zero_at: 15.4             # optional: sigma = 0 at this energy (threshold) before the first point
    pair: H2-electron
    kind: REACTION
    key: H2Ion1-electron-electron
```

The ranges must not overlap; every part must have data in its range. `build` reports how well the two sources agree at every seam
(at the same energy where one source extends into the range of the other, otherwise against an extrapolation), so that a mismatch
between two sources does not go unnoticed. The dataset carries the citations of all parts, `* Parts` with the ranges,
`* Zero at` and the review of every part; `check` warns if one part is not reviewed.

**Why combine?** The reaction e + H₂ → H₂⁺ + 2e needs the *partial* cross-section for H₂⁺ (Yoon Table 13, column H₂⁺), not the
*total* ionization (Table 12 = H₂⁺ + H⁺, the H⁺ part is a reaction of its own). Table 13 starts at 30 eV; below 25 eV the paper
recommends the total cross-section and states that dissociative ionization contributes less than 1 % there, so total ≈ H₂⁺
(Sec. 9). Table 12 is used only where Table 13 has no values; at the seam both sources are compared at the same energy (30 eV:
−1.4 %, the H⁺ part).

### Seeing the parts

```bash
piclas-db build recipe.yaml -o database.h5 --plot-parts plots/     # while building: one plot per combined dataset
piclas-db plot database.h5 --parts                                    # a built file: parts from its provenance (* Parts)
piclas-db plot SpeciesDatabase.h5 --pair H2-electron --key H2Ion1-electron-electron \
    --explain literature/yoon-2008/table12-c1 literature/yoon-2008/table13-c1   # a file without provenance: parts from the numbers
```

The plots show every part in its colour and energy range, the complete data of each source (thin line, from the store), the seams
with the agreement of the sources there, and the zero point. `--explain` finds for every point of an existing dataset the source
with the same energy and value (float32 precision), prints the ranges and the recipe entry that rebuilds the dataset, and lists the
points that come from none of the sources. For `SpeciesDatabase.h5`: 16–25 eV from Table 12 (19 points), 30–1000 eV from Table 13
(39 points), and σ = 0 at 15.4 eV.

This reproduces `H2-electron/REACTION/H2Ion1-electron-electron` of `SpeciesDatabase.h5`: Yoon Table 12 (16–25 eV) and Table 13,
column H₂⁺ (30–1000 eV) give the same 58 values (to the float32 precision of the database); the database starts with σ = 0 at
**15.4 eV**, while the paper gives 15.426 eV as ionization potential.

## Reaction rate tables

Arrhenius parameters k = C T^n exp(−T_d/T_x) of a paper's reaction table are stored as a rate table: one CSV row per reaction and
third body, as printed, with a record that says the unit of C and which chemistry models of a database come from this paper.

```bash
piclas-db literature template author-2001 table2 --page "5 (389)" --table 2 --rates -o work/
# enter the rows in work/table2.csv, set columns.rate.unit and quantity.assignment.chemistry_model (e.g. Author2001)
piclas-db literature add work/table2.extraction.yaml
```

Invented species and values:

```
row,reaction,third_body,C,n,Td,Tx
1,Tx2 + M -> Tx + Tx + M,"Tx, Qq",3.0e22,-1.6,100000,Ta
1,Tx2 + M -> Tx + Tx + M,molecules,7.0e21,-1.6,100000,Ta
2,Tx2 + Qq -> TxQq + Tx,,6.4e17,-1.0,38000,T
3,Tx + e- -> Tx+ + e- + e-,,3.9e33,-3.78,150000,Te
```

* **Species** as printed (N2+, NO+, C+6, e-); third bodies as M or A, with the species of the row in `third_body`: one species, a
  list, `molecules` or `atoms` (ions by their composition, as in DSMC where ions take the properties of their neutral), `others`
  or `all`. A species on both sides (N2 + Ar → N + N + Ar) is the third body too.
* **C** as printed (`3.0e22` or `3.0^22`) in `columns.rate.unit`: `cm^3/(mol s)`, `m^3/(molecule s)`, `cm^3/(molecule s)`,
  `cm^3/s`; the unit applies to the order of the reaction, so termolecular recombinations in such a table are in cm⁶/(mol² s).
  Converted to the PICLas prefactor (m³/s per molecule) when compared.
* **Tx**: T, Ta (√(T T_v)), Tv, Te, Tve, Ttr. T_d may be negative where the paper prints it so.
* `quantity.assignment.chemistry_model`: the suffix of the chemistry models in `AvailableChemistryModels` that cite this paper
  (`Author2001` for `Air_7Spec_9Reac_Author2001`).

`rebuild --explain` compares every Arrhenius reaction of a database with all rate tables in the store ([rebuild.md](rebuild.md)).

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
