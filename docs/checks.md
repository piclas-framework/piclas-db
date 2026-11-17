# Check rules

`piclas-db check <file>` reads a database of any known layout (see [layout.md](layout.md)) and applies the rules below. Findings
have one of three severities, and the exit code is 1 if at least one error is found:

* **ERROR**: PICLas computes something wrong, silently ignores data or aborts
* **WARNING**: inconsistent or risky data
* **INFO**: cosmetic, or a remark on how PICLas treats the data (shown with `--info`)

`--json` prints the findings in machine-readable form, e.g. for CI pipelines.

| Rule | Severity | What is checked | Found in |
| --- | --- | --- | --- |
| `species-attribute-unknown` | ERROR / WARNING | attribute not read by PICLas; ERROR with a suggestion if it looks like a typo | `alpha` instead of `alphaVSS` (SpeciesDatabase.h5) |
| `species-attribute-missing` | ERROR | `MassIC` or `InteractionID` missing | |
| `species-attribute-type` | INFO | `InteractionID` stored as float | |
| `levels-placeholder` | WARNING | placeholder instead of electronic levels (not for `electron` and fully ionized species) | Fe, FeIon1, Xe, XeIon1 (SpeciesDatabase.h5) |
| `levels-ground-state` | ERROR | lowest level not at 0 K, or ground-state degeneracy different from NIST ASD | ArIon1 (SpeciesDatabase.h5), CNIon1 (DSMCSpecies_electronic_state_full_Data.h5) |
| `levels-unit` | ERROR | highest level × hc/k_B equals the ionization energy, i.e. energies in cm⁻¹ instead of K | H (DSMCSpecies_electronic_state_full_Data.h5) |
| `levels-above-ionization` | WARNING | level above the ionization energy | |
| `levels-values`, `levels-degeneracy` | ERROR | negative or non-finite energies, non-integer degeneracies | |
| `levels-unsorted`, `levels-duplicate`, `levels-dummy` | INFO | unsorted levels (PICLas sorts them), equal energies, dummy levels above 1e10 K | Ar (several files) |
| `reaction-attribute-missing` | ERROR | `Reactants`, `Products`, `ReactionModel`, `ChemistryModel`, Arrhenius parameters for TCE | |
| `reaction-species-missing` | ERROR | reactant or product not in `/Species` | |
| `reaction-charge` | ERROR | charge not conserved | |
| `reaction-mass` | WARNING | mass not conserved, i.e. inconsistent `MassIC` (one finding for all reactions) | CO, CO2 (SpeciesDatabase.h5) |
| `xsec-name-unknown` | ERROR / WARNING | group or dataset name not read by PICLas; ERROR with a suggestion if it looks like a typo | `ELECTRONIIC` (XSec_Database_O2_O.h5) |
| `xsec-products-missing` | WARNING | product of a reaction cross-section not in `/Species`: the reaction cannot be used | XeIon2 (SpeciesDatabase.h5) |
| `xsec-undefined` | WARNING | excitation in `UNDEFINED` (not assigned by the converter) | |
| `xsec-threshold-name` | ERROR | excitation dataset name is not a number (PICLas parses the threshold from it) | |
| `xsec-threshold-mismatch` | WARNING | `Threshold [eV]` attribute differs from the dataset name | |
| `xsec-threshold-duplicate` | WARNING | names that are equal as numbers (`14` and `14.0`) | XSec_Database_O2_O.h5 |
| `xsec-reaction-ambiguous` | ERROR | reactions with the same products, distinguished only by their order | XSec_Database_O2*.h5 |
| `xsec-product-order` | WARNING | product order differs from the convention (heavy species first, electrons last); it must match `parameter.ini` | XSec_Database_Xe_Plasma-Biagi7-1.h5 |
| `xsec-reaction-threshold` | WARNING | reaction cross-section starts with σ > 0; PICLas prepends σ = 0 at the heat of reaction | Xe ionization (SpeciesDatabase.h5) |
| `xsec-double-counting` | WARNING | dissociative excitation stored as excitation while the pair also has reactions | O2 (XSec_Database_O2_O.h5), H2 (SpeciesDatabase.h5) |
| `xsec-shape`, `xsec-values`, `xsec-energy-order` | ERROR | shape not (N, 2), negative or non-finite values, decreasing energies | |
| `xsec-energy-duplicate` | ERROR / WARNING | duplicate energy points; ERROR from 3 duplicates on (rounded energies) | ionization (GEC `_1` file), O2 (XSec_Database_O2*.h5) |
| `xsec-magnitude` | WARNING | σ above 1e-16 m² (probably cm²) | |
| `xsec-rounded` | INFO | cross-sections with at most 3 significant digits (compare with the original source) | Ar-ArIon1 (GEC files) |
| `xsec-pair-duplicate` | ERROR | pair stored as A-B and B-A | |
| `xsec-empty-group` | INFO | empty groups | XSec_Database_O2*.h5 |
| `data-float32` | WARNING | data stored as float32 | several files |
| `provenance-missing` | WARNING | species or cross-sections without reference or info | several files |
| `provenance-converter`, `provenance-2d-strings` | INFO | attributes of a generic CSV converter, string attributes stored as 2D arrays | GEC files |
| `file-unreadable`, `file-layout` | ERROR | dataset cannot be read, unknown layout | |

Problems that need a second file or the original source cannot be found by `check` alone. They are covered by `diff` and
`rebuild`: different energy conversion constants, missing species compared to another database, differing sources and values,
data rounded during a conversion, and corrupted characters in references.
