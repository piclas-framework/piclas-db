# Active Thermochemical Tables (ATcT)

ATcT (Argonne National Laboratory, https://atct.anl.gov) provides enthalpies of formation and molar masses. It has a public API, so
piclas-db downloads the records itself: ATcT is the first provider with **automatic download**.

## Finding the ATcT ID

```bash
piclas-db atct search carbon monoxide
```

```
ATcT ID              formula                  charge  dfH(298 K) kJ/mol  HeatOfFormation_K  name (TN version)
630-08-0*0           CO (g)                        0           -110.522          -13292.74  Carbon monoxide (1.228)
630-08-0*1           CO (g, triplet)               0            469.287           56442.25  Carbon monoxide (1.228)
...
```

One formula has several records (phases, electronic states). The gas-phase ground state usually has the suffix `*0`. `--all` also
lists other phases (aqueous, solid). Ions are written `Ar+ (g)`, `[Ar]+2 (g)`, `[ArH]+ (g)`; search by name ("argon cation") if the
formula is not found.

## Using it in a recipe

```yaml
species:
  CO:     {atct: 630-08-0*0, InteractionID: 2}
  ArIon1: {atct: 14791-69-6*0, InteractionID: 10}
```

`build` takes from the record:

| Attribute | From ATcT | |
| --- | --- | --- |
| `HeatOfFormation_K` | ΔfH°(298.15 K) / R | the convention of `SpeciesDatabase.h5`; ions in the stationary-electron (ion) convention, as ATcT |
| `MassIC` | molar mass [u] × 1.66053906892e-27 kg | consistent masses for all species (reactions conserve mass) |

Values written in the recipe take precedence. `build` notes a charge that does not fit the name (`ArIon1` needs charge 1) and records
that are not in the gas phase. The species carries `ATcT <TN version> (<ID>, <formula>): <attributes>` as reference and the stored
record with its sha256 as source.

## Download and store

```bash
piclas-db atct get 630-08-0*0 14791-69-6*0     # download into the store
piclas-db build recipe.yaml -o database.h5      # downloads missing records itself (not with --offline)
```

Every API response is stored unchanged (`atct/<ID>/<date>_<sha8>.json`), with retrieval date, TN version and the configured user,
like a file downloaded by hand; in a store that is a clone of the private repository it is committed. Requests go to
`https://atct.anl.gov/api/v1/species/get/by-atctid/` with a pause of 1 s, a time limit and retries. A record saved by hand (e.g. with
`curl`) can be imported with `piclas-db import record.json --retrieved YYYY-MM-DD`.

## ATcT IDs for an existing database

```bash
piclas-db atct map SpeciesDatabase.h5 --recipe-out atct-species.yaml
piclas-db atct map SpeciesDatabase.h5 --species CO COIon1 --get     # only these, and download the matched records
```

For every species whose reference credits ATcT (35 in `SpeciesDatabase.h5`, `--species` for others), `map`

1. derives formula and charge from the PICLas name (`CO2`, `ArIon1` → Ar with charge 1, `CIon6` → C with charge 6; `electron` is
   skipped),
2. searches ATcT by formula (`Ar+`, `[C]+6`, `CO2`) and by name (`argon cation`, `carbon dioxide`), each term once,
3. keeps gas-phase records with the same composition and charge (`[ArH]+ (g)` is not `ArIon1`, `CO (aq)` is not `CO`), and
4. compares their ΔfH°(298.15 K) with `HeatOfFormation_K × R` of the file: **match** if exactly one record lies within the tolerance
   (default 1 kJ/mol, `--tolerance`; TN versions differ by much less, electronic states and isomers by much more), or the closest
   lies within it and all others more than ten times further away; **check** if none or several do; **not found** without
   candidates.

Example for CO (numbers from the CO check under [Versions](#versions); to be replaced by the output of a real run):

```
CO         match                630-08-0*0 CO (g) TN 1.228, dfH -0.001 kJ/mol vs. file, mass of the file -1.2e-05
```

The line shows the record, the difference of the heat of formation to the file and the relative deviation of the mass of the file
(finding A7). `--recipe-out` writes the matched species as recipe entries (`CO: {atct: 630-08-0*0}`, with `own_data:
own/piclas-parameters`, `--own-data ""` for none) and the others as comments with up to three candidates, to be decided with
`atct search` and entered by hand. `--get` downloads the matched records into the store. The exit code is 0 if every species
matched, 2 if some need a decision, 1 on errors. ATcT is asked at most once per second: all 35 species take about two minutes.

## Versions

The API returns the current thermochemical network (TN) version, e.g. 1.228; every record names it. `SpeciesDatabase.h5` used
version 1.130, so values differ slightly (CO: HeatOfFormation_K −13 292.74 K with 1.228 vs. −13 292.58 K, +1.2e-5). The masses of
ATcT also differ from some masses in `SpeciesDatabase.h5` (CO: −1.2e-5), which explains that 23 CO/CO2 reactions there do not conserve
mass.
