# Comparing databases

`piclas-db diff A.h5 B.h5` compares two databases of any layout (see [layout.md](layout.md)). Both files are read into the same
data model, so a legacy XSec or electronic state database can be compared directly with a current species database.

## Matching

* **Species** by name, electronic and vibrational levels and attributes.
* **Cross-sections** by collision pair (`A-B` equals `B-A`), kind and key: excitation thresholds are compared as numbers (`14`
  equals `14.0`), reaction products independently of their order (`electron-electron-XeIon1` equals `XeIon1-electron-electron`), and
  group names that are probable typos are matched with the intended name (`ELECTRONIIC` with `ELECTRONIC`). Such entries are
  compared and additionally reported as *renamed*.
* **Reactions** by name and attributes; a single-element string array equals a plain string.
* **Diffusion and surface data** by path.

By default, only categories present in both files are compared, e.g. only the species when a legacy electronic state database is
compared with a complete database. `--all` also reports categories that exist in only one file.

## Result classes

| Class | Meaning |
| --- | --- |
| identical | equal within the relative tolerance (`--rtol`, default 1e-6, which covers float32 storage); only counted |
| numerically different | values differ: maximum and median deviation and the affected energy range for cross-sections; number of levels, energies and degeneracies only in one file and the lowest level for electronic levels |
| scaled | all values differ by the same factor, e.g. a different cm⁻¹ → K constant or cm² instead of m² |
| different structure | placeholder vs. levels, different shape, or the same cross-section on a different energy grid |
| attributes differ | attribute only in one file or with a different value |
| renamed | matched entry stored under a different name |
| only in A / only in B | entry exists in one file only |

Entries whose references name different sources (ignoring the retrieval date) are marked `[different source]`.

The exit code is 0 if the files are equal, 1 if they differ and 2 if a file cannot be read. `--json` prints the result in
machine-readable form.

## Examples from existing files

| A | B | Result |
| --- | --- | --- |
| `XSec_Database_O2_O.h5` | `XSec_Database_O2.h5` | 11 identical; O-electron and the O₂ excitations at 6.1, 8.4 and 9.3 eV only in A |
| GEC tutorial file | GEC `_1` file | ionization numerically different, up to +6.4 % at 16 eV (rounded energies) |
| `Electronic-State-Database.h5` | `SpeciesDatabase.h5` | Ar scaled by 1.000193 (different cm⁻¹ → K constant); ArIon1 ground-state degeneracy 4 → 1 |
| `DSMCSpecies_electronic_state_full_Data.h5` | `SpeciesDatabase.h5` | H scaled by 1.43878 (cm⁻¹ instead of K); CNIon1 lowest level differs; CO2Ion1, NCO only in A |
| `XSec_Database_Xe_Plasma-Biagi7-1.h5` | `SpeciesDatabase.h5` | elastic up to −31 % (different source); ionization median −24 %; ionization renamed (product order) |

## Output

On a terminal, the differences are shown as one table per section (Species, Cross-Sections, Reactions, ...), fitted to the
terminal width (long cells are wrapped), with colors unless `NO_COLOR` is set:

```
Species (6)
┌──────┬───────────────────┬───────────┬─────────────────┬────────────┬───────────┐
│ Name │ Item              │ Change    │ A               │ B          │   B/A - 1 │
├──────┼───────────────────┼───────────┼─────────────────┼────────────┼───────────┤
│ Ar   │ HeatOfFormation_K │ attribute │ 0               │ 1          │           │
│      │ MassIC            │ attribute │ 6.633627059e-26 │ 6.6335e-26 │ -1.92e-05 │
├┄┄┄┄┄┄┼┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┼┄┄┄┄┄┄┄┄┄┄┄┼┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┼┄┄┄┄┄┄┄┄┄┄┄┄┼┄┄┄┄┄┄┄┄┄┄┄┤
│ C    │ MassIC            │ attribute │ 1.994e-26       │ 1.9944e-26 │ +2.01e-04 │
│ CO2  │ Ediss_eV          │ only in A │ 5.43            │ -          │           │
│ N2   │ VibrationalLevel  │ structure │ 67 levels       │ no levels  │           │
│ O    │ NewThing          │ only in B │ -               │ 3          │           │
└──────┴───────────────────┴───────────┴─────────────────┴────────────┴───────────┘
```

(`SpeciesDatabase.h5` against a copy with changed attributes.) Numbers have 10 significant digits; `B/A - 1` is given for numeric
attributes. Differences without separate values (e.g. cross-sections that differ numerically) show their description in column A.
Redirected into a file or a pipe (`piclas-db diff A.h5 B.h5 > diff.txt`), the output stays one plain line per difference, and
`--json` gives the structured form (with `item`, `a`, `b`, `relative` where available).
