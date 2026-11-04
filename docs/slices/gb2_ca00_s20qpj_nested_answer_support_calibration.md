# GB2-CA00-S20Q-P-J: Nested Package Calibration Re-run

## Status

`CLOSED - executed successfully; no profile admitted`

## Scope

This Slice re-runs Dataset v4 nested package calibration using the immutable
provider-backed answer-support evidence collected by P-I. It uses the
`CALIBRATION` partition only. It does not call a provider or database, open the
HOLDOUT partition, relax an admission threshold, or activate a runtime policy.

## Frozen Design

The profile shortlist and selection protocol were frozen before the protected
re-run in
`scripts/smoke/data/s136_answer_support_nested_calibration_v1_design.json`.
The four profiles are:

1. `answer-support-second-v1`
2. `answer-support-top-two-v1`
3. `answer-support-class-aware-v1`
4. `answer-support-contradiction-aware-v1`

The selector reconstructs the P-H package feature projection from the
text-free P-I evidence, verifies every evidence and feature hash, joins only
CALIBRATION labels and metadata, and performs five outer folds with four
fold-local inner fits. Each inner threshold fit uses 96 packages. Outer
validation data never participates in profile or threshold selection.

The existing point constraints remain authoritative:

```text
minimum READY recall                 = 0.80
maximum false-READY rate             = 0.10
minimum package AUC                  = 0.80
minimum outer balanced accuracy      = 0.50
maximum outer threshold spread       = 0.20
minimum exact-profile stability      = 4 of 5 outer folds
```

## Protected Re-run

The ignored local report is
`reports/live/gb2_ca00_s20qpj_nested_answer_support_calibration.json`.

```text
source CALIBRATION packages          = 160
source scenarios                     = 80
source provider evaluations          = 160 (reused, not repeated)
new provider calls                   = 0
new database calls                   = 0
READY recall                         = 1.0000
false-READY rate                     = 0.0250
balanced accuracy                    = 0.9875
package AUC                          = 0.99953125
minimum outer balanced accuracy      = 0.96875
outer threshold spread               = 0.0921875
exact stable-profile folds           = 3 of 5
selection                            = NO_ADMISSIBLE_PROFILE
runtime activation                   = disabled
HOLDOUT                              = sealed
```

The outer-fold selections were:

| Fold | Selected profile | Threshold | Balanced accuracy |
| --- | --- | ---: | ---: |
| 0 | `answer-support-contradiction-aware-v1` | 0.5890625 | 0.96875 |
| 1 | `answer-support-top-two-v1` | 0.68125 | 1.00000 |
| 2 | `answer-support-contradiction-aware-v1` | 0.5890625 | 1.00000 |
| 3 | `answer-support-top-two-v1` | 0.65625 | 0.96875 |
| 4 | `answer-support-contradiction-aware-v1` | 0.5890625 | 1.00000 |

The answer-support evidence strongly separates the package labels, but the
exact profile selection split `3:2`. The required `4/5` stability condition is
therefore the only failed admission check. P-J deliberately does not collapse
the two profiles into an equivalence class, prune the shortlist after seeing
the result, or weaken the frozen stability requirement.

## Integrity Binding

```text
generation revision   = hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a
source collection     = sha256:2ef316848a3c3f503856de53e52c80ff9ec94162e59afee966504cb1f8ef530a
design hash           = sha256:982a557cdb1d291e3c722bb005d3d458115ec340215aa94272f535385ca0366f
sample set hash       = sha256:aa8733fce2bc62886d654a91bb77ed419af309cb6347c98cb01adb276038b5bd
selection hash        = sha256:3dad4bc80aad642d7628fe27ec5f06db4016143cfa66d1344f4b1c8332c4cc57
```

No raw query, candidate text, provider output, endpoint, API key, or HOLDOUT
content is stored in the P-J report.

## Verification

```text
focused product/runner tests          = 28 passed
new selector statement/branch         = 100% / 100%
new protected runner statement/branch = 100% / 100%
protected CALIBRATION replay           = PASS
NeX-CX Slice Gate                      = 2,852 passed
repository statement coverage         = 99.10%
repository branch coverage            = 98.26%
contract validation                    = PASS
golden journey transition audit        = PASS
demo-to-product dependency audit       = PASS
```

## Decision

P-J is complete as a successful fail-closed calibration execution. No package
READY profile or threshold is admitted, HOLDOUT remains sealed, and runtime
activation remains prohibited. A later corrective Slice must decide, before
any new evaluation, whether the two empirically similar profiles represent a
pre-declared equivalence family or whether the shortlist and stability
protocol require a new frozen design. That decision must not be retrofitted
inside this Slice.
