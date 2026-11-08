# GB2-CA00-S20Q-P-F: Nested Package-Level Calibration and Admission

## Status

Complete and fail-closed. The frozen P-E package ordinal profiles were
evaluated with Dataset v4 CALIBRATION under the existing 5 outer × 4 inner
scenario-grouped protocol. No candidate/package profile combination satisfied
the frozen admission constraints. P-G, HOLDOUT, and runtime activation remain
prohibited.

## Execution Boundary

P-F reused the immutable P-C-A collection:

```text
database evidence = actual nex_cx_test
embedding revision = hf:5cf2132abc99cad020ac570b19d031efec650f2b
reranker revision  = hf:22e683669bc0f0bd69640a1354a6d0aebcfeede5
source provider calls = 2,240
new P-F provider calls = 0
HOLDOUT calls = 0
```

The nested selector evaluated:

```text
candidate profiles = 4
package ordinal profiles = 4
combinations per outer fold = 16
outer folds = 5
inner folds = 4
inner candidate training rows = 384
outer candidate refit rows = 512 when eligible
```

Candidate probability models and thresholds are fitted only from each inner
training scope. Validation folds receive the frozen model/profile/threshold.
Outer validation and HOLDOUT reselection are prohibited.

## Result

No combination was admitted in any outer fold:

```text
selection = NO_ADMISSIBLE_PROFILE
outer folds with admitted combination = 0 / 5
decision = NO_ADMISSIBLE_PROFILE_STOP_BEFORE_P_G
holdout = SEALED_NOT_OPENED
runtime activation = prohibited
```

Across the 80 outer-fold combination diagnostics:

```text
READY recall range = 0.015625 .. 1.0
false-ready range = 0.0 .. 1.0
balanced accuracy range = 0.4453125 .. 0.59375
```

The strongest safety-oriented diagnostic was
`s20qi-expanded-channel-v1::ordinal-expected-count-v1` in outer fold 0:

```text
balanced accuracy = 0.59375
READY recall = 0.21875
false-ready rate = 0.03125
candidate AUC = 0.74967448
```

Profiles that raised READY recall toward `1.0` also raised false-ready to
approximately `0.80-1.0`. No result simultaneously approached the frozen
`READY recall >= 0.80` and `false-ready <= 0.10` constraints.

## Implementation

`nex_cx.retrieval_package_ordinal_nested_selection` is kept separate from the
existing legacy and Poisson-binomial selectors. It reuses the established:

- candidate profile scoring and fold-local Platt fit;
- Dataset v4 sample and fold validation;
- binary threshold fit/evaluation;
- P-E integrity-checked ordinal feature and score contract.

The selector supports both admission and fail-closed outcomes, full refit
failure, outer refit failure, missing threshold, and profile binding guards.

## Verification

```text
focused regression = 11 passed
new product module statement coverage = 100%
new product module branch coverage = 100%
calibration evidence replay = PASS
provider calls = 0
database calls = 0
holdout calls = 0
NeX-CX Slice Gate = 2,773 passed
repository statement coverage = 99.05%
repository branch coverage = 98.14%
contract validation = PASS
golden journey transition audit = PASS
```

The next step is not P-G or S20Q. A separately reviewed corrective decision is
required because the full frozen package shortlist remains below the admission
boundary. Dataset labels, model revisions, thresholds, and safety constraints
were not changed by P-F.
