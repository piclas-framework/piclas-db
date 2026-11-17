# PICLas database layout

This document specifies the HDF5 layout that PICLas reads via `Particles-Species-Database = database.h5` and that
`piclas-db build` produces. It is derived from the PICLas read paths (Fortran sources on `master`, November 2026) and from the
`SpeciesDatabase.h5` file in the PICLas repository. The names, paths and attributes listed as **read by PICLas** are the contract:
they must match exactly. Everything else (metadata, provenance) is normalized by piclas-db.

Conventions used below:

* Python/h5py notation for shapes: `(N, 2)` means N rows with 2 columns. Fortran sees the transposed array `(2, N)`.
* **req.** = PICLas aborts or reads garbage if missing, **opt.** = PICLas checks for existence and uses a default otherwise.
* Energies of cross-sections in eV, cross-sections in m², electronic and vibrational levels in K.

## Top level

| Group | Content |
| --- | --- |
| `/Species` | one group per species, physical properties as attributes, level datasets |
| `/Reactions` | one dataset per reaction, all information as attributes |
| `/Cross-Sections` | one group per collision pair |
| `/Diffusion-Coefficients` | drift-diffusion transport data (background gas + electrons) |
| `/Surface-Chemistry` | sticking coefficients and catalytic surface reactions |

## `/Species/<name>`

`<name>` is the species name used in `parameter.ini` (`Part-Species[$]-SpeciesName`), e.g. `Ar`, `ArIon1`, `electron`.
Ions are named `<neutral>Ion<charge>`.

### Attributes read by PICLas

| Attribute | Type | Unit | Status | Read in |
| --- | --- | --- | --- | --- |
| `MassIC` | float | kg | req. | `particle_init.f90` |
| `ChargeIC` | float | C | opt. (default 0) | `particle_init.f90` |
| `InteractionID` | int | – | req. | `particle_init.f90` |
| `Tref` | float | K | req. (DSMC) | `dsmc_init.f90` |
| `dref` | float | m | req. (DSMC) | `dsmc_init.f90` |
| `omega` | float | – | req. (DSMC) | `dsmc_init.f90` |
| `alphaVSS` | float | – | opt. (default 1, VHS) | `dsmc_init.f90` |
| `FullyIonized` | logical | – | opt. | `dsmc_init.f90` |
| `HeatOfFormation_K` | float | K | req. (chemistry) | `dsmc_init.f90` |
| `PreviousState` | string | – | opt. (ions: lower ionization state) | `dsmc_init.f90` |
| `SymmetryFactor` | int | – | req. (molecules, chemistry) | `dsmc_chemical_init.f90` |
| `PolyatomicMol` | int (0/1) | – | opt. | `dsmc_init.f90` |
| `LinearMolec` | int (0/1) | – | req. (polyatomic) | `dsmc_polyatomic_model.f90` |
| `NumOfAtoms` | int | – | req. (polyatomic) | `dsmc_polyatomic_model.f90` |
| `CharaTempVib` | float or float array | K | req. (molecules) | `dsmc_init.f90`, `dsmc_polyatomic_model.f90` |
| `CharaTempRot` | float or float(3) | K | alternative to `MomentOfInertia` | `dsmc_init.f90`, `dsmc_polyatomic_model.f90` |
| `MomentOfInertia` | float or float(3) | kg m² | alternative to `CharaTempRot` | `dsmc_init.f90`, `dsmc_polyatomic_model.f90` |
| `Ediss_eV` | float | eV | req. (molecules) | `dsmc_init.f90`, `dsmc_polyatomic_model.f90` |
| `Vib-OmegaE`, `Vib-ChiE` | float | – | opt. (anharmonic oscillator) | `dsmc_init.f90` |

### Datasets read by PICLas

| Dataset | Shape | Columns | Status |
| --- | --- | --- | --- |
| `ElectronicLevel` | `(N, 2)` | degeneracy [–], energy [K] | req. when the electronic model is active |
| `VibrationalLevel` | `(N, 1)` | energy [K] | opt. (currently only N2) |

PICLas sorts the electronic levels by energy after reading (`SortEnergies`), so unsorted levels are tolerated. Species without
electronic levels (e.g. `electron`, fully ionized ions) currently carry a placeholder `[0]` of shape `(1,)`.

### Metadata (not read by PICLas)

`* Created`, `* Reference`. piclas-db writes `* Reference` and `* Source` (provider, dataset, retrieval date, sha256 of the original
file) as UTF-8 strings.

## `/Reactions/<name>`

`<name>` follows `<reactants>_<products>#<k>` with `+` between species, e.g. `CO2+M_CO+M+O#1`, where `M` stands for any
non-reactive partner and `#<k>` distinguishes variants. The dataset content is a dummy scalar; all information is in attributes.
PICLas iterates over all datasets in `/Reactions` and selects those whose `ChemistryModel` contains the model given in
`parameter.ini` (`Particles-Chemistry`, case-insensitive).

| Attribute | Type | Status | Meaning |
| --- | --- | --- | --- |
| `ChemistryModel` | string array `(n, 2)` | req. | per row: model name, non-reactive species list; 1D in old files |
| `NonReactiveSpecies` | string array | opt. | species represented by `M` |
| `ReactionModel` | string | req. | e.g. `TCE`, `QK`, `XSec`, `phIon`, `phIonXSec` |
| `Reactants` | string array | req. | species names, must exist in `/Species` |
| `Products` | string array | req. | species names, must exist in `/Species` |
| `Arrhenius-Prefactor` | float | req. (TCE) | m³/s |
| `Arrhenius-Powerfactor` | float | req. (TCE) | – |
| `Activation-Energy_K` | float | req. (TCE) | K |

The group attribute `AvailableChemistryModels,Reference` lists the chemistry models and their references (metadata).

## `/Cross-Sections/<A>-<B>`

Collision pair of species `A` and `B`. PICLas first looks for `<B>-<A>`, then `<A>-<B>` (in the order of the species in
`parameter.ini`), so only one of the two may exist. Photon pairs are `<A>-photon` (photoionization) or `photon-<A>`.

| Path | Shape | Columns | Read when |
| --- | --- | --- | --- |
| `EFFECTIVE` | `(N, 2)` | energy [eV], σ [m²] | always (used instead of `ELASTIC` if present) |
| `ELASTIC` | `(N, 2)` | energy [eV], σ [m²] | if no `EFFECTIVE` |
| `BACKSCATTER` | `(N, 2)` | energy [eV], σ [m²] | ion–neutral charge exchange |
| `VIBRATION/<threshold>` | `(N, 2)` | energy [eV], σ [m²] | vibrational excitation |
| `ELECTRONIC/<threshold>` | `(N, 2)` | energy [eV], σ [m²] | electronic excitation |
| `REACTION/<products>` | `(N, 2)` | energy [eV], σ [m²] | reactions with `ReactionModel = XSec` |
| `SPECTRUM/<pair>` | `(N, 2)` | photon energy, intensity | photoionization |

Rules taken from the read code:

* **Thresholds are parsed from the dataset name** (`READ(dsetname,*)`), so the names of `VIBRATION` and `ELECTRONIC` datasets must
  be numbers in eV. A typo in the group name (e.g. `ELECTRONIIC`) is not an error for PICLas: the group is silently ignored.
* Datasets in a group are iterated **in alphabetical order of their names**, not numerically.
* **Reaction cross-sections are found by name**: `<products>` is built from the products of the reaction as defined in
  `parameter.ini`, joined by `-` **in that order** (e.g. `ArIon1-electron-electron`). The order of the products in the dataset name
  therefore has to match the reaction definition. Supported are 2 to 4 products.
* If the first σ of a reaction cross-section is greater than 0, PICLas prepends the point (heat of reaction, σ = 0), i.e. the
  threshold region is linearly interpolated. PICLas aborts if the heat of reaction is more than 10 times the first energy.
* Old standalone XSec databases (`Particles-CollXSec-Database`) have the same pair groups directly in the root, without
  `/Cross-Sections`; PICLas still reads them.

## `/Diffusion-Coefficients/<background species>-electron/<database>`

Used with `BGGas-DriftDiff-Database = <database>` (drift-diffusion builds only). `<background species>` are the background gas
species joined by `-`, e.g. `Ar-electron/Biagi-v7.1`.

| Dataset | Content |
| --- | --- |
| `DIFFUSION` | diffusion coefficient vs. reduced field |
| `MOBILITY` | mobility vs. reduced field |
| `IONIZATION` | ionization coefficient vs. reduced field |
| `ENERGY` | mean energy vs. reduced field |

## `/Surface-Chemistry`

| Path | Content | Read in |
| --- | --- | --- |
| `StickingCoefficient` | `(N, 4)` table, required for boundaries with a sticking-coefficient model | `particle_boundary_init.f90` |
| `<CatName>` | catalytic reaction: attribute `Type` (req.) and optional attributes `ReactHeat`, `HeatScaling`, `EnergyAccommodation`, `MinimumTotalCoverage`, `MaximumTotalCoverage`, `MinimumTemperature`, `MaximumTemperature`, `StickingCoefficient`, `EqConstant`, `DissOrder`, `LateralInteraction`, `Ca`, `Cb`, `Prefactor`, `Energy` | `surfacemodel_chemistry.f90` |

## Legacy layouts

| Layout | Structure | Mapping to the current layout |
| --- | --- | --- |
| Legacy XSec database (`XSec_Database_*.h5`, `LXCat_Database_*.h5`) | `/<A>-<B>/...` in the root | `/Cross-Sections/<A>-<B>/...`, product order of reactions has to be checked |
| Legacy electronic state database (`DSMCSpecies_electronic_state_*.h5`, `Electronic-State-Database.h5`) | `/<species>` `(N, 2)` in the root | `/Species/<species>/ElectronicLevel` |

## What piclas-db normalizes

piclas-db writes the names and attributes read by PICLas exactly as listed above and normalizes everything else:

* all numerical data as float64, all strings as UTF-8, integer attributes as integers;
* one provenance scheme (`* Reference`, `* Source` with sha256 of the original file) on every dataset or species group;
* cross-section thresholds additionally as attribute `Threshold [eV]` (the dataset name stays the number PICLas parses);
* energy conversion with the exact constant hc/k_B = 1.438776877 cm K;
* electronic levels sorted by energy, ground state at 0 K;
* reaction cross-sections starting at the threshold with σ = 0 where the original data provide it.
