# GB2-CA00-S20Q-P-K: Exact-Profile Stability and Semantic Equivalence Audit

## Status

`CLOSED - profiles are distinct; fresh canonical design required`

## Scope

This Slice audits whether the two profiles that split the P-J outer-fold
selection may be treated as one equivalence family. It reuses immutable P-I
provider evidence and the P-J nested selection result. It does not call a
provider or database, access HOLDOUT, alter a score or threshold, authorize an
equivalence family, or activate a runtime policy.

The compared exact profiles are:

1. `answer-support-top-two-v1`
2. `answer-support-contradiction-aware-v1`

## Frozen Audit Contract

The audit criteria were frozen before the protected execution in
`scripts/smoke/data/s136_answer_support_profile_equivalence_audit_v1_design.json`.

```text
maximum OOF decision disagreement       = 0.05
minimum score ordering agreement        = 0.98
complete fold-local thresholds required = true
equal feature dependency sets required  = true
counterfactual response equality        = true
counterfactual delta tolerance           = 1e-9
```

The audit separates empirical closeness from semantic equivalence. Passing
only the empirical checks cannot retroactively authorize an equivalence
family. Even if every check passes, the result permits only a future
pre-declared design review.

## Implementation

The product audit module validates P-I/P-J bindings and P-J selection
integrity, refits each exact profile inside every outer-fold CALIBRATION
training partition, compares OOF decisions and full-CALIBRATION pairwise score
ordering, and evaluates frozen counterfactual probes. Missing thresholds,
package coverage mismatch, malformed evidence, source drift, or incomplete
diagnostics fail closed.

The protected runner:

- reconstructs text-free samples from P-I evidence;
- verifies the P-J no-admission boundary and immutable hashes;
- records no raw query, candidate text, endpoint, or credential;
- records zero new provider and database calls;
- keeps HOLDOUT sealed and runtime activation disabled.

## Protected Audit Result

The ignored local report is
`reports/live/gb2_ca00_s20qpk_profile_stability_equivalence_audit.json`.

```text
CALIBRATION scenarios                  = 80
CALIBRATION packages                   = 160
outer folds compared                   = 5
OOF decision disagreements             = 3 / 160
OOF decision disagreement rate         = 0.01875
score ordering agreement               = 0.90589623
fold-local thresholds complete         = true
feature dependency sets equal          = false
counterfactual responses equivalent    = false
equivalence family authorized          = false
HOLDOUT                                = sealed
runtime activation                     = disabled
decision                               = DISTINCT_PROFILES_FRESH_DESIGN_REQUIRED
```

The OOF decisions are close enough under the frozen 5% criterion, but the
score ordering agreement is below 98%. The profiles are also semantically
different:

| Probe | Contradiction-aware delta | Top-two delta |
| --- | ---: | ---: |
| contradiction sensitivity | -0.1975 | 0.0 |
| classification-fraction sensitivity | -0.15 | 0.0 |

`answer-support-top-two-v1` depends only on the second support score and
top-two support mean. `answer-support-contradiction-aware-v1` additionally
depends on classification fraction, contradiction, and normalized margin
signals. Their near OOF decisions therefore do not establish semantic
equivalence.

## Integrity Binding

```text
source collection = sha256:2ef316848a3c3f503856de53e52c80ff9ec94162e59afee966504cb1f8ef530a
P-J selection     = sha256:3dad4bc80aad642d7628fe27ec5f06db4016143cfa66d1344f4b1c8332c4cc57
nested design     = sha256:982a557cdb1d291e3c722bb005d3d458115ec340215aa94272f535385ca0366f
audit design      = sha256:3f200bdbcc9bff519f9868dcaaa9873fa1d24652a7534c30b627aeabfb7e0ff8
audit result      = sha256:3f1df25d117b26e7a3d133d56960ccd04118f3a5ff5e881e262072893b0fcaa8
```

## Verification

```text
focused product/runner tests          = 27 passed
new product statement/branch          = 100% / 100%
new protected runner statement/branch = 100% / 100%
protected CALIBRATION audit            = PASS
NeX-CX Slice Gate                      = 2,873 passed
repository statement coverage         = 99.11%
repository branch coverage            = 98.28%
contract validation                    = PASS
golden journey transition audit        = PASS
demo-to-product dependency audit       = PASS
```

## Decision

P-K is complete. The two profiles must remain distinct, no equivalence family
or threshold is admitted, and S20Q HOLDOUT acceptance remains blocked. The
next corrective Slice must freeze one canonical profile or a genuinely new
profile design before collecting fresh CALIBRATION evidence. It must not reuse
this post-result comparison as authorization for a retroactive equivalence
family.
