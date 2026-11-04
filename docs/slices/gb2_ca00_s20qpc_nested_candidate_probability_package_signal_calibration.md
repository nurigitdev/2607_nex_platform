# GB2-CA00-S20Q-P-C: Nested Candidate-Probability Package Signal Calibration

## Status

Complete and fail-closed. Candidate relevance probability is fitted only from
each nested training fold and projected to package `P(relevant count >= 2)`.
No profile satisfied the frozen Dataset v4 admission constraints, so HOLDOUT
remains sealed and runtime activation remains prohibited.

## Boundary

This Slice adds a second package-signal evaluator without replacing the legacy
second-highest candidate score path. The same live calibration collection is
used for an inner-diagnostic comparison only.

The candidate probability model is fitted at these scopes:

- inner training fold: 384 candidates;
- outer training refit: 512 candidates;
- final calibration refit, only after nested admission: 640 candidates.

The model, profile, and threshold are never fitted from outer validation or
HOLDOUT data. A future admitted profile must also pass the five-repeat package
READY invariance contract introduced by S20Q-P-C-A.

## Protected Live Result

The protected run used actual `nex_cx_test` PostgreSQL and the immutable live
provider bindings:

```text
embedding revision = hf:5cf2132abc99cad020ac570b19d031efec650f2b
reranker revision  = hf:22e683669bc0f0bd69640a1354a6d0aebcfeede5
embedding calls    = 1,440
reranking calls    = 800
total calls        = 2,240
provider failures  = 0
holdout calls      = 0
```

Calibration-only inner diagnostics:

| Signal | READY recall range | False READY range | Balanced accuracy range |
| --- | ---: | ---: | ---: |
| Candidate probability `P(count >= 2)` | `0.046875-0.203125` | `0.015625-0.265625` | `0.4609375-0.5703125` |
| Legacy second-highest | `0.03125-1.0` | `0.046875-1.0` | `0.4140625-0.5` |

The probability signal reduced worst-case false READY behavior but did not
reach the minimum READY recall requirement. The authoritative result is:

```text
selection = NO_ADMISSIBLE_PROFILE
decision = NO_ADMISSIBLE_PROFILE_KEEP_HOLDOUT_SEALED
holdout = SEALED_NOT_OPENED
runtime activation = prohibited
```

Local redacted evidence:

`reports/live/gb2_ca00_s20qpca_vector_near_tie_boundary.json`

## Verification

The final NeX-CX Slice Gate passed:

```text
tests = 2,766 passed
statement coverage = 99.04%
branch coverage = 98.11%
nested selection = 97.84% statement / 94.64% branch
P-C runner = 100% statement / 100% branch
contract validation = 230 schemas / 291 examples /
                      245 negative examples / 10 OpenAPI documents
```
