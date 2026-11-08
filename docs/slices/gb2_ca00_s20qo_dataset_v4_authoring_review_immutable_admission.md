# GB2-CA00-S20Q-O: Dataset v4 Authoring, Review, and Immutable Admission

## Status

Complete. The 100-scenario dataset v4 corpus is authored, reviewed through a
distinct reviewer role, admitted fail-closed, and frozen by both file and
semantic digests. Its deterministic nested fold plan is materialized and
frozen separately. No provider was called, no holdout score was inspected,
and no runtime calibration policy was activated.

## Objective

S20Q-M froze the dataset size and nested-selection protocol. S20Q-N made its
schema, admission rules, and fold assignment executable. S20Q-O supplies the
reviewed canonical content required by those contracts while preserving the
blind holdout boundary.

## Canonical Artifacts

Dataset:

```text
path = scripts/smoke/data/s136_retrieval_package_calibration_v4.json
schema = model_calibration_dataset.v4
dataset id = s136-retrieval-package-confidence-public-v4
file sha256 = a0be13e113efee2a4a2dd904aaab6d65916a4e31b4a71b91465b66210d9dea20
semantic sha256 = 594209203d25b0a87e6fd136b6794bdc30058a5eb45b7e2c8ff27523bd7f1757
```

Nested fold plan:

```text
path = scripts/smoke/data/s136_retrieval_package_calibration_v4_folds.json
file sha256 = f38fdcd955d07b6d1692dca2a8cdf7c22a2fdffe1ce7d5206a780aa2297d2720
semantic hash = sha256:6e01aa5792b3d18f67a39419a37622f9c8df6e8124e981b04151496180de4613
outer folds = 5
inner folds per outer training set = 4
```

## Authoring Composition

The final dataset contains:

```text
scenario pairs = 100
packages = 200
candidates = 800
CALIBRATION scenarios = 80
HOLDOUT scenarios = 20
READY / LOW_CONFIDENCE packages = 100 / 100
```

The 30 v3 scenarios had already been exposed to earlier calibration and
holdout executions. They are therefore preserved exactly, except that all are
classified as v4 CALIBRATION. No v3 scenario is admitted into the v4 holdout.

The new material consists of:

```text
new CALIBRATION scenarios = 50
new HOLDOUT scenarios = 20
```

The 70 new scenarios cover distinct Project, Finance, Identity/Authorization,
Governance/Operations, and AI Runtime rules. Each pair contains a supported
READY request and a separately scoped unsupported-detail request. The
LOW_CONFIDENCE package includes a close but insufficient passage, a related
policy, an unsupported contradictory assertion, and an unrelated negative.
It is not constructed by negating the READY label or swapping candidate
labels.

## Frozen Quotas

Language scenarios:

| Partition | Korean | Korean-English mixed | English | Total |
| --- | ---: | ---: | ---: | ---: |
| CALIBRATION | 48 | 16 | 16 | 80 |
| HOLDOUT | 12 | 4 | 4 | 20 |

Domain scenarios:

| Partition | Project | Finance | Identity | Governance | AI runtime | Total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| CALIBRATION | 16 | 20 | 12 | 12 | 20 | 80 |
| HOLDOUT | 4 | 5 | 3 | 3 | 5 | 20 |

Across the 200 queries and 800 candidate passages, normalized exact duplicate
text count is zero.

## Review Boundary

Every scenario has one author reference and one distinct reviewer reference.
The 30 inherited scenarios identify their v3 curation origin; the 70 new
scenarios identify the v4 authoring role. All 100 records are bound to the
separate v4 review role and record:

```text
review_status = APPROVED
semantic_near_duplicate_status = REVIEWED_NO_CONFLICT
model_score_guided_authoring = false
mechanical_paraphrase = false
```

The admission manifest intentionally excludes query text, candidate text,
author references, and reviewer references.

## Immutable Admission

`scripts/quality/check_retrieval_calibration_v4_dataset.py` fails closed on:

- dataset file or semantic digest drift;
- fold-plan file, materialization, or semantic digest drift;
- v3 inherited case removal or content changes beyond CALIBRATION partition;
- reuse of any exposed v3 scenario in the v4 holdout;
- dataset/design binding, quota, review, or fold-assignment drift.

The checker recomputes the fold plan from the admitted dataset and frozen
S20Q-M design before comparing it with the stored artifact. The fold artifact
contains scenario IDs and bounded stratum counts only; it contains no query or
candidate text and no holdout scenario ID.

## Verification

Focused immutable checker verification:

```text
6 passed
checker statement coverage = 100.00%
checker branch coverage = 100.00%
ruff = PASS
retrieval_calibration_v4_dataset=pass
scenarios=100 calibration=80 holdout=20 packages=200 candidates=800 folds=5x4
```

Focused dataset, fold, and checker regression:

```text
63 passed
combined focused coverage = 99%
```

Contract validation:

```text
contract_validation=pass
schemas=230 examples=291 negative_examples=245 openapi=10
```

NeX-CX Slice Gate:

```text
2,752 passed
statement coverage = 99.06% (minimum 95.00%)
branch coverage = 98.24% (minimum 94.00%)
immutable checker = 100.00% statement / 100.00% branch
contract validation = 230 schemas / 291 examples /
                      245 negative examples / 10 OpenAPI documents
golden journey transition audit = PASS
demo-to-product dependency audit = PASS
```

## Safety Boundary

S20Q-O does not:

- call embedding, reranking, generation, or any other remote provider;
- execute calibration, fit weights or thresholds, or open holdout labels to
  an evaluator;
- change the frozen four-profile shortlist or admission thresholds;
- modify dataset v1, v2, or v3 bytes;
- activate the incumbent 4B/4B model combination;
- add a PostgreSQL migration or persistence dependency.

## Handoff

The next corrective Slice may collect provider evidence for the 80
CALIBRATION scenarios and run the frozen nested profile-selection protocol.
It must not read or score the 20 HOLDOUT scenarios until calibration-only OOF
admission has passed:

`S20Q-P: Dataset v4 Calibration Collection and Nested Profile Selection`
