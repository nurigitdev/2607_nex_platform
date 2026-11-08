# GB2-CA00-S20Q-M: Dataset v4 Expansion and Nested Selection Protocol Design Freeze

## Status

Complete. The dataset v4 authoring target and nested profile-selection
protocol are frozen before any v4 text is authored, any provider is called,
or the sealed holdout is opened. Dataset v3 remains immutable and the current
Qwen3-Embedding-4B plus Qwen3-Reranker-4B combination remains a non-admitted
incumbent baseline.

## Objective

S20Q-L established that dataset v3 has 160 candidate rows but only 20
independent calibration scenario pairs. Its single-level group-CV procedure
searches 455 profiles and reports performance on the same folds used for
selection. The package semantics are correct; the effective sample size and
selection procedure are not strong enough for runtime admission.

S20Q-M freezes the corrective design without changing a model, threshold, or
runtime policy. It defines:

1. the number and stratification of independent v4 scenario pairs;
2. the authoring and independent-review boundary;
3. a small evidence-backed profile shortlist;
4. nested, stratified, scenario-grouped cross-validation;
5. calibration, holdout, and runtime activation boundaries.

## Frozen Artifact

The canonical design artifact is:

```text
path = scripts/smoke/data/s136_retrieval_package_calibration_v4_design.json
schema = cx_retrieval_calibration_design.v1
design id = s136-retrieval-package-confidence-v4-design
status = FROZEN_NOT_AUTHORED
file sha256 = 84cbde0665bc4bfa5218c5e363f026651bf57a16d850c9e10d7cdc16d36a2e24
semantic hash = sha256:f467d2c7ba37e0b314add4961a573dad8a9f800db58762ba3644456352585a2a
```

`retrieval_calibration_design.py` admits the design fail-closed and returns a
bounded manifest. `check_retrieval_calibration_v4_design.py` also freezes the
file digest so whitespace, field, quota, profile, or boundary drift is
detected before implementation or data authoring proceeds.

## Dataset v4 Target

The independent unit remains one scenario pair: one READY package and one
LOW_CONFIDENCE package with matching domain, language, and partition.

```text
scenario pairs = 100
CALIBRATION = 80
HOLDOUT = 20
packages = 200
candidates = 800
packages per scenario = 2
candidates per package = 4
```

Partition language quotas:

| Partition | Korean | Korean-English mixed | English | Total |
| --- | ---: | ---: | ---: | ---: |
| CALIBRATION | 48 | 16 | 16 | 80 |
| HOLDOUT | 12 | 4 | 4 | 20 |

Partition domain quotas:

| Partition | Project | Finance | Identity | Governance | AI runtime | Total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| CALIBRATION | 16 | 20 | 12 | 12 | 20 | 80 |
| HOLDOUT | 4 | 5 | 3 | 3 | 5 | 20 |

The quotas preserve the reviewed v3 proportions while increasing the
calibration error-rate resolution from `0.05` to `0.0125`. The 20-scenario
holdout has `0.05` resolution and is used only once after a calibration-only
candidate passes.

## Package Semantics

The S20Q-L audit found no reason to change package meaning. Dataset v4 keeps:

```text
READY meaning = at least two relevant candidates
package score = second-highest candidate score
candidate truth at runtime = prohibited
```

A READY package contains `PRIMARY_ANSWER`, `SUPPORTING_ANSWER`,
`HARD_NON_ANSWER`, and `EASY_NON_ANSWER`. A LOW_CONFIDENCE package contains
`HARD_NON_ANSWER`, `RELATED_NON_ANSWER`, `CONTRADICTORY_NON_ANSWER`, and
`EASY_NON_ANSWER`.

Each scenario requires an author and a distinct independent reviewer.
Model-score-guided authoring and mechanical paraphrase are prohibited.
Normalized text must be unique, and semantic near-duplicates require explicit
review. Holdout labels may not be exposed to the calibration executor.

## Pre-Frozen Profile Shortlist

The 455-profile search is replaced by four profiles grounded in prior live
evidence:

| Profile | Source | Weights |
| --- | --- | --- |
| `reranker-only-v1` | S20Q-I single-signal diagnostic | reranker `1.0` |
| `s20qh-three-signal-balanced-v1` | S20Q-H live best effort | reranker `0.3`, RRF `0.4`, channel rank `0.3` |
| `s20qk-three-signal-channel-v1` | S20Q-K 4B baseline | reranker `0.3`, RRF `0.3`, channel rank `0.4` |
| `s20qi-expanded-channel-v1` | S20Q-I live best effort | reranker `0.6`, channel rank `0.3`, BM25 quality `0.1` |

The design permits at most five profiles, but only these four are admitted.
Adding or changing a profile requires a new design revision; it cannot occur
during nested evaluation.

## Nested Selection Protocol

Assignment is deterministic by scenario group and stratified by domain and
language using `SHA256_STRATIFIED_ROUND_ROBIN_V1` with the frozen seed
`s136-v4-nested-cv-v1`.

```text
outer folds = 5
outer validation scenarios per fold = 16
outer training scenarios per fold = 64
inner folds = 4
inner validation scenarios per fold = 16
```

For each outer fold:

1. keep the 16 outer scenarios unseen;
2. run four-fold grouped CV over the 64 outer-training scenarios;
3. select only `profile_id` and threshold in the inner loop;
4. fit the selected profile threshold on all 64 outer-training scenarios;
5. evaluate the frozen profile and threshold on the outer 16 scenarios;
6. prohibit profile, weight, feature, or threshold reselection from outer
   results.

Selection is constraint-first. Admissible inner results are ordered by
balanced accuracy, READY recall, lower false-ready rate, candidate AUC, and
finally the frozen shortlist order. A profile must be selected in at least
four of five outer folds. No-admissible-profile is a valid fail-closed result;
best-effort metrics cannot authorize holdout access.

After calibration OOF admission, the stable profile is refit on all 80
calibration scenarios. Only its threshold may be fitted; features and weights
remain frozen. That profile and threshold are then evaluated once on the
20-scenario holdout without reselection.

## Admission Boundary

The point constraints remain authoritative:

```text
maximum false-ready rate = 0.10
minimum READY recall = 0.80
minimum candidate AUC = 0.70
minimum outer-fold balanced accuracy = 0.50
maximum outer threshold spread = 0.20
pipeline repeat count = 5
```

Two-sided Wilson 95% intervals must be reported for visibility, but S20Q-M
does not silently replace the frozen point constraints with a new confidence
interval gate. Changing that admission meaning requires a separate reviewed
decision.

Calibration OOF must pass before the holdout is opened. Holdout must pass in
one execution. Runtime activation still requires a separate approval after
both gates; a successful holdout does not activate a policy automatically.

## Explicit Exclusions

S20Q-M does not:

- author dataset v4 cases or define their final semantic digest;
- modify dataset v3 bytes or its admission contract;
- call PostgreSQL, embedding, reranking, or generation providers;
- inspect any existing or future holdout score;
- select a model revision;
- relax false-ready or recall thresholds;
- activate the incumbent 4B/4B profile.

## Verification

Focused design and checker verification:

```text
37 passed
design admission module = 100% statement / 100% branch
immutable checker = 100% statement / 100% branch
ruff = PASS
retrieval_calibration_v4_design=pass
scenarios=100 calibration=80 holdout=20 profiles=4
```

NeX-CX Slice Gate:

```text
2,724 passed
statement coverage = 99.05% (minimum 95.00%)
branch coverage = 98.22% (minimum 94.00%)
design admission module = 100.00% statement / 100.00% branch
immutable checker = 100.00% statement / 100.00% branch
contract validation = 229 schemas / 291 examples /
                      245 negative examples / 10 OpenAPI documents
golden journey transition audit = PASS
demo-to-product dependency audit = PASS
```

## Handoff

The next corrective Slice should implement the v4 dataset schema and the
deterministic stratified fold-assignment primitive, without authoring the 100
scenario pairs yet:

`S20Q-N: Dataset v4 Schema and Nested Fold Assignment Foundation`

Dataset authoring should begin only after that executable contract can reject
quota, pairing, reviewer, leakage, and fold-assignment drift.
