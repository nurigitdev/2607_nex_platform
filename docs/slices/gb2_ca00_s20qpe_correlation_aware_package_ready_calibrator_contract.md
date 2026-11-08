# GB2-CA00-S20Q-P-E: Correlation-Aware Package READY Calibrator Contract

## Status

Complete. A finite, explainable package ordinal-score contract is frozen for
P-F nested calibration. It removes the Poisson-binomial conditional-
independence claim but does not admit a profile, select a threshold, open
HOLDOUT, or activate runtime behavior.

## Decision

P-D showed that candidate relevance remained directional while
`P(relevant count >= 2)` lost package-level separation. P-E therefore treats
the package output as an ordinal score rather than another probability.

The frozen feature vector is:

```text
expected_relevant_fraction
second_candidate_probability
top_two_probability_mean
probability_at_least_half_fraction
```

All fields are produced from candidate probabilities without candidate truth.
They are bounded to `[0, 1]`, integrity-hashed, and bound to the source
candidate-probability model and retrieval profile.

## Frozen Shortlist

P-E freezes four simple non-negative profiles:

1. `ordinal-expected-count-v1`
2. `ordinal-top-two-support-v1`
3. `ordinal-balanced-support-v1`
4. `ordinal-conservative-support-v1`

These are candidates, not approved policies. No profile may be added or tuned
after P-F starts without a new design version. Negative weights, label-derived
runtime fields, HOLDOUT fitting, and outer-validation fitting are prohibited.

The immutable design source is:

`scripts/smoke/data/s136_package_ordinal_calibrator_v1_design.json`

## Implementation

`nex_cx.retrieval_package_ready_calibrator` provides:

- frozen design validation and semantic hashing;
- integrity-checked package feature projection;
- deterministic ordinal scoring for one frozen profile;
- explicit `ORDINAL_SCORE_NOT_PROBABILITY` semantics;
- fail-closed safety metadata.

The P-E design fixture proves deterministic direction only. It is not
calibration evidence and cannot be used for admission.

## Verification

```text
focused regression = 7 passed
new product module statement coverage = 100%
new product module branch coverage = 100%
contract smoke = PASS
provider calls = 0
database calls = 0
holdout calls = 0
```

The next Slice, P-F, may evaluate only this frozen shortlist with Dataset v4
CALIBRATION nested folds. It must preserve `NO_ADMISSIBLE_PROFILE` as a valid
fail-closed result.
