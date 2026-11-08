# GB2-CA00-S20Q-P-G: Package READY Identifiability and Error Topology Audit

## Status

Complete. Dataset v4 CALIBRATION evidence was replayed without provider,
database, or HOLDOUT access. Candidate relevance remained directional, but no
frozen candidate/package score combination could satisfy both package safety
constraints. The authoritative decision is `ANSWERABILITY_SIGNAL_REQUIRED`.

## Boundary

P-G consumes two immutable predecessor artifacts:

- P-C-A role-bearing, uncertainty-aware repeatability evidence;
- P-F nested package admission evidence with `NO_ADMISSIBLE_PROFILE`.

The audit does not change Dataset v4, labels, folds, retrieval features, model
revisions, thresholds, or runtime behavior. It evaluates CALIBRATION only and
emits no query text, document text, vector, endpoint, database URL, or secret.

```text
calibration scenarios = 80
calibration packages = 160
calibration candidates = 640
candidate profiles = 4
package ordinal profiles = 4
evaluated combinations = 16
new provider calls = 0
new database calls = 0
HOLDOUT calls = 0
```

## Identifiability Result

The best safety-oriented diagnostic was:

```text
combination = s20qi-expanded-channel-v1::ordinal-expected-count-v1
candidate AUC = 0.75131510
package AUC = 0.51390625
paired positive-over-negative direction = 0.5625

at false-ready <= 0.10:
  READY recall = 0.2125
  false-ready = 0.0625
  balanced accuracy = 0.575

at READY recall >= 0.80:
  READY recall = 0.80
  false-ready = 0.8375
  balanced accuracy = 0.48125
```

Across all 16 combinations, package AUC ranged from `0.32234375` through
`0.51390625`. No threshold satisfied both `READY recall >= 0.80` and
`false-ready <= 0.10`.

This is not a narrow threshold-selection failure. The safety frontier requires
rejecting 63 of 80 READY packages, while the recall frontier incorrectly
accepts 67 of 80 low-confidence packages.

## Role Topology

The selected candidate profile separated easy negatives but did not reliably
separate answer support from difficult non-answers:

| Negative role | Answer/support versus role AUC |
| --- | ---: |
| `HARD_NON_ANSWER` | `0.54078125` |
| `CONTRADICTORY_NON_ANSWER` | `0.69828125` |
| `RELATED_NON_ANSWER` | `0.74492187` |
| `EASY_NON_ANSWER` | `0.99156250` |

Mean candidate probabilities were:

```text
PRIMARY_ANSWER = 0.44963465
SUPPORTING_ANSWER = 0.25975435
HARD_NON_ANSWER = 0.33336185
CONTRADICTORY_NON_ANSWER = 0.25014038
RELATED_NON_ANSWER = 0.23107610
EASY_NON_ANSWER = 0.07133541
```

`HARD_NON_ANSWER` therefore scored above `SUPPORTING_ANSWER` on average. The
current relevance-oriented signals can recognize obvious irrelevance, but do
not encode whether a topically related candidate answers, supports, declines
to answer, or contradicts the query.

## Error Topology

At the best safety point, READY recall was low across every domain:

```text
AI_RUNTIME = 0.10
FINANCE = 0.25
GOVERNANCE_OPERATIONS = 0.16666667
IDENTITY_AUTHORIZATION = 0.33333333
PROJECT = 0.25
```

The result is also not confined to one language profile:

```text
ENGLISH = 0.00
KOREAN = 0.27083333
KOREAN_ENGLISH_MIXED = 0.25
```

The largest package-feature correlation was `0.87232822` between expected
relevant fraction and top-two probability mean. Reweighting correlated
transformations of the same candidate-relevance signal is not accepted as a
substitute for a new answerability signal.

## Decision

```text
decision = ANSWERABILITY_SIGNAL_REQUIRED
existing signal recalibration = not justified
threshold relaxation = prohibited
dataset or label mutation = not authorized
model revision change = not authorized
HOLDOUT = SEALED_NOT_OPENED
runtime activation = prohibited
```

The next reviewed boundary should define a provider-neutral, calibration-only
answer-support and contradiction evidence contract. Candidate truth remains
forbidden as runtime input. P-H must not select a provider, open HOLDOUT, or
activate a policy; live signal collection belongs to a later Slice.

## Implementation

`nex_cx.retrieval_package_identifiability_audit` provides:

- integrity-checked replay of role-bearing candidate observations;
- exhaustive threshold Pareto analysis for the frozen 16 combinations;
- candidate-role overlap and package-feature correlation diagnostics;
- domain and language error topology at the best safety point;
- bounded corrective decisions and fail-closed safety metadata.

`run_gb2_s20qpg_package_ready_identifiability_audit.py` binds the audit to the
actual P-C-A and P-F evidence and the immutable Dataset v4 CALIBRATION metadata.

## Verification

```text
focused regression = 13 passed
product audit module statement coverage = 100%
product audit module branch coverage = 100%
protected runner statement coverage = 100%
protected runner branch coverage = 100%
protected evidence replay = PASS
provider calls = 0
database calls = 0
holdout calls = 0
NeX-CX Slice Gate = 2,779 passed
repository statement coverage = 99.06%
repository branch coverage = 98.17%
contract validation = PASS
golden journey transition audit = PASS
demo-to-product dependency audit = PASS
```

P-G stops before P-H. S20Q HOLDOUT acceptance and S20R closure remain blocked
until a separately reviewed answerability contract passes CALIBRATION-only
nested admission.
