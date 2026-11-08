# GB2-CA00-S20Q-L: Calibration Dataset and Package-Level Relevance Policy Audit

## Status

Complete. Dataset v3 and the package-level READY policy are structurally
valid, but the calibration experiment does not have enough independent
scenarios for its profile-search space. The current Qwen3-Embedding-4B and
Qwen3-Reranker-4B combination remains the incumbent baseline, but is not
admitted for runtime activation.

## Objective

S20Q-J and S20Q-K showed that larger reranker and embedding revisions did not
meet the unchanged package-level safety constraints. S20Q-L therefore audits
the calibration design before changing another model. It answers four
questions:

1. what is the effective independent sample count;
2. whether the package READY label and score match the intended evidence
   semantics;
3. whether profile selection is statistically credible at the current sample
   size;
4. whether the incumbent 4B/4B decision is reproducible under an exact
   immutable model and policy binding.

The S20Q holdout remains sealed. This Slice does not relax a threshold,
activate a policy, or select a new model.

## Implementation

`retrieval_candidate_relevance_calibration.py` now exposes a bounded profile
outcome diagnostic. It reconstructs the exact group-CV fold thresholds and
candidate rankings used by a supplied calibration profile, verifies that the
reconstructed confusion matrix matches the persisted out-of-fold metrics,
and returns candidate identifiers and scores without document text.

`retrieval_calibration_policy_audit.py` admits only:

- the exact dataset v3 calibration binding;
- immutable Qwen3-Embedding-4B and Qwen3-Reranker-4B revisions;
- completed, fail-closed calibration evidence with sealed holdout;
- a matching historical execution under the same model and policy binding.

The protected S20Q-L runner reuses the existing S20Q-E and S20Q-I live
collection path. It does not add a second retrieval implementation. Evidence
contains bounded metrics, scenario identifiers, domain/language strata,
candidate roles, and hashes. Raw prompts, document content, vectors,
endpoints, database URLs, and credentials are excluded.

## Dataset and Policy Audit

Dataset v3 contains 40 packages and 160 candidate rows, but its independent
unit is the positive/negative package pair for one scenario. The effective
sample size is therefore 20, not 160.

| Property | Audited value |
| --- | ---: |
| independent scenario pairs | 20 |
| packages | 40 |
| candidates | 160 |
| relevant candidates | 40 |
| non-relevant candidates | 120 |
| cross-validation folds | 5 |
| validation scenarios per fold | 4 |
| validation labels per class per fold | 4 |
| searched profiles | 455 |
| profiles per independent scenario | 22.75 |
| profiles per package | 11.375 |

The package contract is semantically correct:

- READY means at least two relevant candidates are present;
- the package score is the second-highest candidate score;
- candidate truth labels are calibration-only and are not runtime inputs.

The concern is selection capacity, not label meaning. Four labels per class
in each validation fold make fold-level error rates move in `0.25` steps.
Overall false-ready and recall rates move in `0.05` steps. Searching 455
profiles with the same single-level group CV used for selection and reporting
creates a high selection-bias risk at this effective sample size.

The frozen constraints remain unchanged:

- maximum false-ready rate: `0.10`, at most 2 of 20 negative packages;
- minimum READY recall: `0.80`, at least 16 of 20 positive packages.

## Protected Live Evidence

The protected run used actual `nex_cx_test`, the immutable 4B embedding and
4B reranker artifacts, 160 persisted documents, 40 retrieval packages, five
full-pipeline repeats, restart readback, and cleanup. It completed 360 live
embedding requests and 200 live reranking requests with all protected checks
passing.

| Metric | Historical S20Q-K A | Fresh S20Q-L | Frozen requirement |
| --- | ---: | ---: | ---: |
| false-ready rate | 0.15 | 0.10 | <= 0.10 |
| READY recall | 0.60 | 0.65 | >= 0.80 |
| balanced accuracy | 0.725 | 0.775 | - |
| minimum fold balanced accuracy | 0.375 | 0.50 | >= 0.50 |
| candidate AUC | 0.80354167 | 0.83375 | >= 0.70 |
| threshold spread | 0.00087771 | 0.00113508 | <= 0.20 |

The fresh run passed the false-ready boundary but recovered only 13 of the
required 16 READY packages. Seven positive packages were false low-confidence
and two negative packages were false ready. Positive package score exceeded
its paired negative in 14 of 20 scenarios; the negative scored higher in six.

Failures were not confined to one domain: AI runtime, finance, governance,
identity, and project scenarios were all represented. The selected feature
profile also changed under the exact immutable model and policy binding. The
admission decision remained `NO_ACCEPTABLE_POLICY`, but the metric movement
confirms that the current selection procedure is sensitive to the small
calibration sample.

```text
audit hash = sha256:9690c64496e4d2755649a7fe27e363b972d24f7f6df2204477c2f3d8373ca4f6
local evidence sha256 = 7904b1e3ec97183f950e04e81e3905b628f0093aeb16bc33d2e1ac54fb069111
holdout access = prohibited
runtime activation = prohibited
threshold relaxation = prohibited
```

## Decision

```text
status = CORRECTIVE_DATASET_AND_POLICY_DESIGN_REQUIRED
incumbent = Qwen3-Embedding-4B + Qwen3-Reranker-4B
incumbent disposition = KEEP_AS_BASELINE_NOT_ADMITTED
next action = DATASET_V4_EXPANSION_AND_NESTED_SELECTION_DESIGN
```

Dataset v3 remains frozen as an immutable historical and regression baseline.
The next corrective design must:

1. increase the number of independently reviewed scenario pairs across the
   existing domain and language strata;
2. size dataset v4 from the desired confidence and error resolution instead
   of treating candidate rows as independent samples;
3. use nested group cross-validation or a small profile set fixed before
   final calibration scoring;
4. preserve scenario-pair grouping and the second-highest package rule;
5. keep holdout access sealed until a calibration-only policy satisfies the
   frozen constraints;
6. compare a model revision only after the corrected dataset and selection
   design can distinguish model quality from calibration variance.

## Verification

Focused verification before the Slice Gate:

```text
18 passed
audit module = 99% statement coverage
profile diagnostic module = 98% statement coverage
protected runner = 100% statement coverage
ruff = PASS
```

Protected execution:

```text
gb2_s20ql_calibration_policy_audit=pass
decision=CORRECTIVE_DATASET_AND_POLICY_DESIGN_REQUIRED
false_ready_excess=0
true_ready_deficit=3
actual PostgreSQL identity/readback/cleanup = PASS
live embedding/reranking collection = PASS
holdout sealed = PASS
```

NeX-CX Slice Gate:

```text
2,691 passed
statement coverage = 99.04% (minimum 95.00%)
branch coverage = 98.21% (minimum 94.00%)
profile diagnostic module = 98.38% statement / 95.37% branch
audit module = 99.17% statement / 97.37% branch
protected runner = 100.00% statement / 100.00% branch
contract validation = 229 schemas / 291 examples /
                      245 negative examples / 10 OpenAPI documents
golden journey transition audit = PASS
demo-to-product dependency audit = PASS
```

S20Q-L is closed as a source-backed and protected-live negative admission
decision. Dataset v4 design is the next corrective boundary; another model
rollout or holdout execution is not authorized by this result.
