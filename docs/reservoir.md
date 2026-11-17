# Reservoir validation with PICLas

`piclas-db reservoir` validates a database with PICLas itself: it generates reservoir simulations, in which PICLas counts the
reactions of a projectile species with a background gas in a single cell without performing them, as in the `NIG_Reservoir`
regression checks of PICLas (e.g. `CHEM_RATES_XSec_Chem_H2-e`). The rate coefficients PICLas reports are compared with the rate
coefficients expected from the cross-sections in the database.

## Generate a study

```bash
piclas-db reservoir database.h5 --pair Ar-electron --energies 16 20 50 100 -o study/        # monoenergetic beam
piclas-db reservoir database.h5 --pair H2-electron --temperatures 1e4:1e5:5 -o study/      # Maxwell distribution
```

| Mode | Projectiles | Background | Expected rate coefficient |
| --- | --- | --- | --- |
| beam (`--energies`, eV) | `velocityDistribution = constant`, v = sqrt(2E/μ) | 300 K | k = σ(E) v |
| Maxwell (`--temperatures`, K) | `maxwell_lpn` at T | `maxwell_lpn` at T | k(T) = ⟨σ v⟩ with the reduced mass μ (as `piclas-db plot --rate`) |

The study contains:

* `study.yaml`: pair, species, reactions, settings and, per point, the expected rate coefficients and the expected number of
  counted reactions
* `hopr.ini`: single cell of 4.64 µm (volume 1e-16 m³), as in the regression checks
* one directory per energy or temperature with a `parameter.ini`: `Particles-DSMCReservoirSim`, `...SimRate` and `...Statistic`,
  `CalcReacRates = T`, MCC with null collisions, the species and reactions from `Particles-Species-Database` (products in the order
  of the dataset names, which PICLas matches literally)
* `run.sh`: creates the mesh (hopr or pyhope) and runs PICLas (`PICLAS=<binary>`, built with `PICLAS_TIMEDISCMETHOD=DSMC`) for
  every point

The time step limits the collision probability per step (`--collision-probability`, default 0.01), and the number of steps is chosen so that about `--events`
reactions (default 1e4, about 1 % statistical error) are counted for the rarest reaction (at most 50000 steps). Points below a
threshold run 100 steps, where no reaction may be counted. Where a reaction cross-section starts with σ > 0, the expected value
uses the zero point at the heat of reaction (from `HeatOfFormation_K`) that PICLas prepends. Reactions whose products are not in
`/Species` are skipped and listed.

PICLas computes collision probabilities as 1 − exp(−nσg·Δt), so the counted rate coefficient is lower than nσg by about half the
collision probability. A first study for Ar-electron with a collision probability of 0.05 showed exactly this: −2.5 % at 16 eV
decreasing to −1.7 % at 100 eV (where the excitation cross-sections, which PICLas does not use without the electronic model, make up
a larger part of the total cross-section). With the default of 0.01 the bias is about −0.5 %, below the statistical error: the same study repeated with 0.01 gave
−0.91 %, −1.87 %, −0.83 % and −0.66 % at statistical errors of 1.0 %, 1.0 %, 0.65 % and 0.56 % (weighted mean −0.9 ± 0.4 %,
consistent with the expected −0.4 % to −0.5 %), without any point marked as systematic.

Options: `--projectile` (default: electron or the ion of the pair), `--reactions` (only these reaction cross-sections),
`--background-density` (1e22 m⁻³), `--projectile-density` (1e21 m⁻³), `--events`.

## Evaluate

```bash
PICLAS=~/piclas/build/bin/piclas study/run.sh
piclas-db reservoir --evaluate study/ [--tolerance 0.05]
```

The last line of `PartAnalyze.csv` (columns `NNN-ReactionMMM`) of every point is compared with the expected rate coefficient. A
point passes if the deviation is within the tolerance (default 5 %) or within three standard deviations of the counting statistics;
below a threshold no reaction may be counted. Points within the tolerance but more than three standard deviations away are marked
`(systematic?)`; if several deviate in the same direction, a systematic effect is reported. The table and `study/rates.png` (rate coefficients from the database as lines, PICLas
as points) show the result; the exit code is 1 if a point failed or was not run.
