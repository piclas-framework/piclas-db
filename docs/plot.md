# Plots

```bash
piclas-db plot SOURCE [SOURCE ...] --pair Ar-electron [--kind ...] [--key ...] [--compare] [--rate] -o figure.png
piclas-db plot SOURCE [SOURCE ...] --species H -o levels.png
piclas-db plot SOURCE --list
```

Sources can be any combination of database files (any layout), table directories (`piclas-db export`) and original downloads
(LXCat text files, NIST ASD level exports), e.g. the LXCat download, the ASCII tables and the built `database.h5` in one figure.
The same cross-section is drawn in the same color in every source (matched as in `piclas-db diff`: pair order, thresholds as
numbers, product order and typos in group names do not matter), each source with its own line style. Legend labels are the file
names or `--label`.

| Option | Figure |
| --- | --- |
| `--pair` | cross-sections σ(E) of a collision pair, log-log; `--kind` and `--key` select cross-sections |
| `--compare` | additional panel with the relative deviation of every source from the first one (where σ is above 1 % of its maximum) |
| `--rate` | Maxwellian rate coefficients k(T) = sqrt(8/(π μ)) (k_B T)^(-3/2) ∫ σ(E) E exp(−E/k_B T) dE over `--temperatures` (default 1e3:1e5 K); heavy-particle pairs need `MassIC` of both species in one of the sources |
| `--species` | electronic levels: cumulative degeneracy Σg over the level energy in eV; unit errors and missing or extra levels show up as shifted or different steps |
| `--list` | collision pairs and species of the sources |

The output format follows the file extension of `-o` (`.png`, `.pdf`, `.svg`). Plots are written to files only, so they also work on
HPC login nodes without a display.

Examples with existing files:

* LXCat download vs. GEC-reference-cell file, `--pair Ar-ArIon1 --compare`: deviations of ±0.4 % over the whole energy range, the
  rounding of the old file
* `XSec_Database_Xe_Plasma-Biagi7-1.h5` vs. `SpeciesDatabase.h5`, `--pair Xe-electron --kind ELASTIC REACTION --compare`: elastic
  −31 % to +19 %, ionization about −25 % above 30 eV
* the same with `--rate`: the ionization rate coefficients of both databases
* `DSMCSpecies_electronic_state_full_Data.h5` vs. `SpeciesDatabase.h5`, `--species H`: the old levels end at 9.45 eV instead of 13.6
  eV (energies in cm⁻¹ instead of K)

`piclas-db diff` also accepts original downloads, e.g. `piclas-db diff lxcat_download.txt database.h5`.

## Combined datasets

`plot --parts` shows datasets built from several extractions (recipe `parts`), `plot --explain SOURCE ...` finds the parts of an
existing dataset from its numbers; `build --plot-parts DIR` writes the plots while building. See [literature.md](literature.md#seeing-the-parts).
