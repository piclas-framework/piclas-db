# T6 Rate tables from papers

How the Arrhenius parameters of a paper's reaction table get into the store, so that a database can be built from them. Two worked
examples: a table that piclas-db reads from the PDF (Farbar and Boyd 2008), and a scanned table that is entered by hand and
checked by double entry (Park 1993).

Prerequisites: [T3](T3-adding-data.md) (identity, importing papers). The papers are not shipped with piclas-db: use your own
copies, or the ones in your group's store ([T4](T4-private-repository.md)).

| Paper | Table | Kind of PDF |
| --- | --- | --- |
| E. Farbar, I. Boyd, Simulation of Fire II Reentry Flow Using the DSMC Method, AIAA 2008-4103, doi:10.2514/6.2008-4103 | 2, PDF page 9 | text layer |
| C. Park, Review of chemical-kinetic problems of future NASA missions. I - Earth entries, JTHT 7(3), 1993, doi:10.2514/3.431 | 2, PDF page 5 | scan |

## 1. The papers into the store

```bash
piclas-db import 2008-Farbar-Simulation-of-Fire-II.pdf --literature -n     # check: key farbar-2008, DOI found
piclas-db import 2008-Farbar-Simulation-of-Fire-II.pdf --literature
piclas-db import 1993-Park-Review-of-Chemical-Kinetic-Problems.pdf --literature park-1993
piclas-db literature list
```

From here on, piclas-db works with the papers in the store, by key: every value can be traced to the stored file.

## 2. What a rate table is

A rate table holds the Arrhenius parameters k = C T^n exp(-T_d/T_x) of a paper's table, one row per reaction and third body:

```csv
row,reaction,third_body,C,n,Td,Tx
1M,N2 + M -> N + N + M,molecules,1.162e-8,-1.6,113200,T
```

* `reaction` in rate-table notation: `+` between species, `->` as arrow, ions `N2+`, the electron `e-`, third bodies `M` or `A`
* `third_body`: species (`N`, `"N2, O2, NO"` for several with the same rate), or a class: `molecules`, `atoms`, `others`, `all`
* `C` as printed: `1.162e-8`, `3.0^22`, `7.00x10^21`; its unit is in the record (`cm^3/(mol s)`, `m^3/(molecule s)`, ...)
* `n`, `Td` in K, `Tx` the controlling temperature: `T`, `Ta` (√(T Tv)), `Tv`, `Te`, `Tve`, `Ttr`

Next to it, the record (`.extraction.yaml`) says where the table is (paper, page, table), the unit, the chemistry model that cites
the paper, the mixture, how it was made (`method`), and notes on every decision.

## 3. A table with a text layer: Farbar 2008

**Extract.** One command reads the table and writes two pairs of files: the raw copy (the table as printed) and the rate table
converted from it:

```bash
mkdir -p ~/work/rates && cd ~/work/rates
piclas-db extract farbar-2008 --page 9 --table 2 --rates air --chemistry-model Farbar2008 -o farbar-2008
```

```
table 2 (pages 9, text): 47 rows, 3 columns -> farbar-2008/table2-raw.csv
  caption: Table 2: Reaction rate coefficients in m3/molecule/s.
  raw copy: farbar-2008/table2-raw.extraction.yaml
  rate table: 46 row(s) converted -> farbar-2008/table2-rates-air.csv, record farbar-2008/table2-rates-air.extraction.yaml
    unit of C: m^3/(molecule s); chemistry model: Farbar2008
    check: A taken as atoms: check the paper
    check: M taken as molecules: check the paper
    check: not converted: 15F: digit groups '77 2000' irregular (misprint?) in '1.660×10^−18T0.500exp(-77 2000/T)'
```

**Correct what is listed,** each with a note in the record:

* row 15F: the paper prints "77 2000"; the value is 77,200 K. Add the row by hand:
  `15F,O + NO+ -> O2 + N+,,1.66e-18,0.5,77200,T`
* M and A: Farbar's table does not list the species; molecules and atoms is the reading of the DSMC code the paper describes
  (keep, with a note)

```yaml
notes:
- 'row 15F: printed "77 2000", entered as 77200'
- M taken as molecules, A as atoms (DSMC classes; the paper lists no species)
```

**Check without storing.** Every row as piclas-db understands it, and, with a database, each row looked up among its reactions:

```bash
piclas-db literature add -n farbar-2008/table2-rates-air.extraction.yaml --compare SpeciesDatabase.h5
```

`=` the database has a reaction with these values, `≠` the closest one and what differs, `–` none (recombinations, which PICLas
computes from the forward rate).

**Store both,** the raw copy and the rate table:

```bash
piclas-db literature add farbar-2008/table2-raw.extraction.yaml
piclas-db literature add farbar-2008/table2-rates-air.extraction.yaml
```

Both are `pending` until reviewed (section 5).

## 4. A scanned table: Park 1993, by double entry

A scan has no text layer; piclas-db can read it only by OCR, and OCR misreads exactly what matters in such tables: small
exponents (3.0²² read as 3.077), subscripts (N₂ read as N,), stacked charges (N₂⁺), the subscript of Tₐ. So a scanned table is
entered by hand, twice: two readings made independently from the page, compared row by row.

**The two readers.** Usually two people; one of them may also be another source made from the page (an earlier transcription).
What matters: neither reading is copied from the other.

**The OCR copy as a reading aid** (reactions and species are mostly readable, numbers are not to be trusted):

```bash
piclas-db extract park-1993 --page 5 --table 2 --ocr --columns reaction,M,Tx,C,n,Td,skip -o park-1993/ocr
```

`--columns` names the role of each column of the table from left to right (here: Reaction, M, Tₓ, C, n, T_d, Source).

**Two empty rate tables,** one per reader:

```bash
piclas-db literature template park-1993 table2-rates-air --rates --page 5 --table 2 -o park-1993/first
piclas-db literature template park-1993 table2-rates-air --rates --page 5 --table 2 -o park-1993/second
```

In both records: `columns.rate.unit: cm^3/(mol s)`, `quantity.assignment.chemistry_model: Park1993`, `quantity.mixture: air`,
`method: manual`.

**Each reader enters the table from the page** (zoom in; the scan is the only reference):

1. the reaction as printed: `N2 + M -> N + N + M`
2. one row per third-body rate; species with the same rate may share a row: `"N, O"`; the electron row of N2 + M is its own
   row (`e-`, C 1.2^25)
3. C with its exponent: `3.0^22`. Look at every exponent twice: 21 and 22, 15 and 17 are easy to confuse in a scan
4. n with its sign (`-1.60`), T_d without the thousands comma (`113200`)
5. Tₓ: `Ta`; where a row leaves it empty, the value of the reaction's first row
6. a misprint is entered as printed, with a note: Park's table prints `NO + M -> O + O + M` (the products should be N + O).
   The decision is the same for both readers (as printed), so that the comparison does not show it as a difference
7. radiative recombination (hν) is not entered: not an Arrhenius reaction for PICLas

**Each reader checks their own table:**

```bash
piclas-db literature add -n park-1993/first/table2-rates-air.extraction.yaml
```

It lists rows it cannot read (typos in species or numbers) and reactions that are not balanced: the NO + M misprint appears here,
as it should.

**Compare the two readings:**

```bash
piclas-db literature compare park-1993/first/table2-rates-air.extraction.yaml park-1993/second/table2-rates-air.extraction.yaml
```

```
47 row(s) agree, 2 difference(s):
  differs:            N2 + M -> N + N + M [O2]: C 7e+21 vs. 7e+22
  only in the second: O2 + M -> O + O + M [NO+] (row 12)
Look up every difference on the page: one of the two readings is wrong there, or a decision (misprint) differs.
```

For every line, look at the page and correct the reading that is wrong; run `compare` again until it says
`the two readings agree`. Then one of the two is the table to store. Add a note on how it was made:

```yaml
method: manual
notes:
- entered twice from the scan (double entry by <first reader> and <second reader>), compared with literature compare
- 'NO + M -> O + O + M as printed (products should be N + O)'
```

**Check against the database and store:**

```bash
piclas-db literature add -n park-1993/first/table2-rates-air.extraction.yaml --compare SpeciesDatabase.h5
piclas-db literature add park-1993/first/table2-rates-air.extraction.yaml
```

No raw copy is stored for a scan: the OCR copy was only an aid.

## 5. Review

Someone who did not make the table reviews it against the page:

```bash
piclas-db literature list                                  # page, table, kind, rows, method, review status
piclas-db literature review farbar-2008/table2-rates-air --approve --notes "checked row by row against page 9"
piclas-db literature review park-1993/table2-rates-air --approve --notes "double entry, differences resolved on the page"
```

Only approved tables are used by builds. A table with an error: correct the CSV and `literature add` again (a new version), or
`--reject` with `--notes`.

## 6. Using the tables

A recipe names the rate table and row of each reaction ([T5](T5-recipes-and-build.md), section 7, and [rebuild.md](../rebuild.md)):

```yaml
reactions:
  N2+M_N+M+N#2:
    rates: literature/farbar-2008/table2-rates-air
    row: 1M
    third_body: molecules
    models:
      Air_11Spec_43Reac_Farbar2008: N2,O2,NO,N2Ion1,O2Ion1,NOIon1
```

`piclas-db rebuild --explain` compares the reactions of an existing database with all rate tables in the store.

## Checklist

- [ ] paper in the store (`import --literature`), key and DOI checked
- [ ] text layer: `extract --rates`, every `check:` item corrected or kept with a note
- [ ] scan: entered twice independently, `literature compare` agrees
- [ ] unit, chemistry model, mixture and method set in the record
- [ ] `literature add -n` (with `--compare` against a database where there is one) shows no unexplained difference
- [ ] stored with `literature add`, reviewed by someone else
