# GB2-CA00 Post-S20J Model Calibration Corrective Execution Plan v1.0

**Status:** PLANNED / SOURCE-BACKED / LIVE CALIBRATION CORRECTIVE

**Program:** NeX Platform v2.1

**Parent baseline:** GB2-CA00-S20J Coverage Hardening Closure

**Observed live evidence:** GB2-CA00-S20J Remote Provider Live Evidence Follow-Up

**Observed commit:** `e45aac5f`

**Observed date:** 2026-11-02

## 1. Purpose

This plan defines the corrective work required after the canonical
`Qwen3-Reranker-4B` live calibration returned
`NO_ACCEPTABLE_THRESHOLD`. The immediate objective is not to weaken the
existing safety constraints or choose the best-looking threshold from a small
sample. It is to establish enough labelled evidence to decide whether a
single reranker score can safely represent retrieval confidence.

The corrective sequence shall:

1. preserve the existing 36-sample dataset as an immutable regression asset;
2. introduce a representative 120-sample v2 dataset;
3. separate threshold selection from holdout acceptance by query group;
4. verify live score identity and repeatability for the admitted model;
5. evaluate the single-signal policy under the unchanged safety constraints;
6. introduce multi-signal calibration only if single-signal separation remains
   insufficient;
7. resume the deferred protected live acceptance matrix only after an admitted
   calibration decision exists.

## 2. Source-Backed Entry Baseline

The current dataset is:

```text
path              = scripts/smoke/data/s136_reranker_calibration_v1.json
dataset id        = s136-reranker-relevance-public-v1
query cases       = 12
labelled pairs    = 36
positive          = 12
negative          = 24
case shape        = 1 positive + 1 same-domain negative + 1 easy negative
```

The protected live execution against `Qwen3-Reranker-4B` observed:

```text
sample count                  = 36
candidate threshold count     = 73
status                        = NO_ACCEPTABLE_THRESHOLD
best-effort threshold         = 0.88611
best-effort false-ready rate  = 0.29166667
best-effort ready recall      = 0.66666667
best-effort balanced accuracy = 0.6875
positive score range          = 0.826644 .. 0.944872
negative score range          = 0.740984 .. 0.937475
score overlap                 = 0.110831
```

The frozen constraints remain:

```text
maximum false-ready rate = 0.10
minimum ready recall     = 0.80
minimum sample count     = 20
minimum positive count   = 8
minimum negative count   = 8
```

The observed result is materially outside both principal constraints. More
samples may confirm or refine the finding, but shall not be assumed to make
the current single-signal policy pass.

## 3. Dataset Versioning Decision

The v1 dataset remains immutable:

```text
s136-reranker-relevance-public-v1
  purpose = historical regression and score-drift comparison
  action  = retain unchanged
```

A separate v2 dataset shall be introduced:

```text
s136-reranker-relevance-public-v2
  target query cases    = 30
  candidates per query  = 4
  total labelled pairs  = 120
  positive pairs        = 60
  negative pairs        = 60
```

Each query group contains exactly:

```text
STRONG_POSITIVE       expected_ready=true
ACCEPTABLE_POSITIVE   expected_ready=true
HARD_NEGATIVE         expected_ready=false
EASY_NEGATIVE         expected_ready=false
```

`relevance_grade` is the auditable label. `expected_ready` remains the binary
calibration target and is derived consistently from the grade. A document may
not be copied between calibration and holdout groups.

## 4. Dataset Composition

### 4.1 Language allocation

The 30 query groups target the actual Korean-default Platform workload:

| Language profile | Query groups | Labelled pairs |
| --- | ---: | ---: |
| Korean | 18 | 72 |
| Korean/English mixed terminology | 6 | 24 |
| English | 6 | 24 |
| Total | 30 | 120 |

### 4.2 Domain allocation

The majority of cases shall represent NeX Platform business use:

- project creation, membership, status, and profitability;
- voucher, expense, account, amount, date, and evidence handling;
- organization, employee, role, approval, and authority;
- contract, retention, security, and operational procedure;
- RAG, embedding, reranking, runtime, and incident operations.

General-knowledge cases may remain only as easy-negative controls. They shall
not dominate threshold selection.

### 4.3 Hard-negative requirements

Hard negatives must exercise confusable business semantics, including:

- same domain but a different requested action;
- correct action for the wrong project, account, user, date, or amount;
- policy versus procedure, request versus approval, and create versus update;
- semantically related text that does not answer the query;
- negation, exception, expired policy, and superseded version;
- Korean queries with English business terms and the inverse.

Near-duplicate wording that leaks the label is prohibited.

## 5. Calibration and Holdout Boundary

Dataset partitions are assigned by complete query group, not by individual
document. This prevents a query or paraphrase from appearing on both sides.

```text
calibration partition = 20 query groups = 80 labelled pairs
holdout partition     = 10 query groups = 40 labelled pairs
```

The calibration partition selects candidate thresholds. The holdout partition
is opened only after the candidate rule is frozen. Re-selecting a threshold
from holdout results invalidates the run and requires a new dataset version.

Point metrics remain canonical for compatibility. Wilson confidence intervals
for false-ready rate and ready recall shall also be reported as uncertainty
evidence, but this first 120-pair dataset does not claim final production-grade
statistical power by itself.

## 6. Live Evidence and Repeatability

Every live score record shall bind:

```text
provider capability
model name and revision
deployment id
request shape
score semantics
retrieval policy id
dataset id and SHA-256
case id and document id
execution timestamp
repeat index
```

Raw query and document text shall not be written to protected evidence files.
The admitted dataset remains the source of labelled text.

The full v2 dataset is executed at least twice against the same admitted model
revision. Score variance, rank inversion, missing candidates, non-finite
scores, model identity drift, and response-shape drift are fail-closed
conditions. Repeatability evidence must be reviewed before threshold fitting.

## 7. Single-Signal Decision Gate

The first decision uses reranker native score only and keeps the current
constraints unchanged.

`SINGLE_SIGNAL_ADMITTED` requires:

```text
live model identity stable
all 120 labelled pairs scored
repeatability checks pass
calibration partition produces an acceptable threshold
the frozen threshold passes the untouched holdout partition
false-ready rate <= 0.10
ready recall >= 0.80
```

If admitted, the profile remains model-revision and dataset-hash specific.
Changing the model revision, request shape, score semantics, or retrieval
policy invalidates the admission.

`MULTI_SIGNAL_REQUIRED` is the expected fail-closed outcome when no acceptable
single threshold exists. It is not a test failure and shall not be converted
into PASS by relaxing constraints.

## 8. Multi-Signal Boundary

Multi-signal work begins only after `MULTI_SIGNAL_REQUIRED` is recorded. The
initial candidate features are:

- reranker native score and top-1/top-2 margin;
- vector similarity and vector rank;
- BM25 score and lexical rank;
- weighted RRF score and fused rank;
- agreement between vector, lexical, and reranker ordering;
- evidence count and permission-filtered candidate coverage.

The corrective sequence shall prefer deterministic, explainable calibration
over a new opaque model. Feature normalization, missing-signal behavior, and
decision reason codes must be versioned. Tenant, owner, and permission signals
remain admission filters and may not be traded against relevance confidence.

## 9. Canonical Slice Order

### GB2-CA00-S20K: Calibration Dataset v2 Contract Freeze

- freeze v1 as immutable regression evidence;
- define the v2 schema, relevance grades, partition rules, language/domain
  quotas, and dataset admission checks;
- add deterministic ID, label consistency, duplicate, leakage, and digest
  validation.

Remote provider required: **No**.

### GB2-CA00-S20L: 120-Sample Dataset Authoring and Admission

- author 30 query groups and 120 labelled pairs;
- perform label and hard-negative review;
- generate the canonical dataset digest and partition manifest;
- prove that v1 remains unchanged.

Remote provider required: **No**.

### GB2-CA00-S20M: Live Score Collection and Repeatability

- execute all v2 pairs twice against the canonical reranker;
- verify model/revision/request-shape identity and complete score coverage;
- record redacted repeatability and drift evidence;
- stop on response, identity, score, or rank instability.

Remote provider required: **Yes, reranker**.

Gate: focused regression, protected live execution, then Checkpoint Gate.

### GB2-CA00-S20N: Single-Signal Calibration and Holdout Decision

- fit candidate thresholds on the calibration partition only;
- freeze the selected threshold before opening holdout evidence;
- calculate point metrics, confusion matrix, score overlap, and confidence
  intervals;
- record `SINGLE_SIGNAL_ADMITTED` or `MULTI_SIGNAL_REQUIRED`.

Remote provider required: **No**, when S20M evidence is complete.

This is a mandatory decision gate.

### GB2-CA00-S20O: Provider Score-Semantics and Request-Profile Audit

- audit model card/runtime behavior, request shape, instruction/template
  behavior, score interpretation, normalization, and revision binding;
- compare v1 and v2 score distributions without changing labels to fit output;
- determine whether the overlap is a provider-profile issue or a genuine
  single-score limitation.

Remote provider required: **Yes for confirmation replay**.

S20O is required when S20N returns `MULTI_SIGNAL_REQUIRED`.

### GB2-CA00-S20P: Multi-Signal Calibration Contract and Evaluator

- define versioned feature extraction and missing-signal semantics;
- implement deterministic calibration and decision reason codes;
- prevent permission or ownership signals from becoming relevance features;
- add adversarial, malformed, replay, and model-revision mismatch tests.

Remote provider required: **No** for deterministic implementation.

### GB2-CA00-S20Q: Multi-Signal Live Holdout Acceptance

- collect a complete permission-filtered hybrid retrieval feature package;
- evaluate the frozen multi-signal policy against untouched holdout groups;
- bind the admitted profile to model revision, retrieval policy, tokenizer,
  chunk policy, and dataset digest;
- perform actual CX PostgreSQL and remote embedding/reranking acceptance.

Remote provider required: **Yes, embedding and reranker**.

Gate: protected live execution and Checkpoint Gate.

### GB2-CA00-S20R: Calibration Closure and Deferred Live Matrix Replay

- publish the final admitted or rejected calibration decision;
- rerun the deferred S136, S137, S140, S147, S149, and S150 protected live
  acceptance in dependency order;
- record PostgreSQL cleanup and zero-residue evidence;
- run the Repository Full Gate and publish the corrective As-Built record.

Remote provider required: **Yes, embedding, reranker, and generation**.

## 10. Stop Conditions

Implementation stops for review when any of the following occurs:

- a label is ambiguous under the declared relevance-grade policy;
- calibration and holdout query groups are not independent;
- provider model or revision differs from the admitted identity;
- repeated executions show unexplained score or rank instability;
- a candidate is missing, duplicated, non-finite, or reordered without trace;
- evidence would expose raw dataset text, endpoint, credential, or DB secret;
- satisfying the metric requires weakening the frozen safety constraints;
- a multi-signal feature would bypass permission or ownership admission;
- a database migration or public contract change becomes necessary without a
  separately reviewed decision.

## 11. Non-Goals

This plan does not authorize:

- changing v1 labels or deleting the prior failed evidence;
- increasing samples by duplicating or mechanically paraphrasing cases;
- selecting a threshold from the holdout partition;
- lowering false-ready or recall constraints to obtain PASS;
- hard-coding behavior for `Qwen3-Reranker-4B` in platform code;
- treating a provider HTTP success as calibration acceptance;
- resuming release acceptance while calibration status is unresolved.

## 12. Entry Decision

Implementation begins with `GB2-CA00-S20K`. S20K and S20L may be completed in
an environment without remote-provider connectivity. S20M is the first Slice
that requires the live reranker. S20N is the mandatory single-signal decision
gate; S20O through S20Q execute only when that decision requires multi-signal
calibration. S20R closes the sequence only after the protected live matrix and
Repository Full Gate pass.
