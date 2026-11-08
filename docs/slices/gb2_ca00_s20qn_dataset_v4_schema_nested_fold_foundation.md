# GB2-CA00-S20Q-N: Dataset v4 Schema and Nested Fold Assignment Foundation

## Status

Complete. The dataset v4 machine-readable contract, fail-closed admission,
and deterministic nested fold-assignment foundation are implemented. This
Slice does not author the 100 scenario pairs, execute a provider, inspect a
holdout score, or activate a runtime calibration policy.

## Objective

S20Q-M froze the dataset v4 size, stratification, review, and nested-selection
protocol before any v4 text was authored. S20Q-N turns that frozen design into
an executable boundary that can reject quota, pairing, review, leakage, and
fold-assignment drift before authoring begins.

## Dataset v4 Contract

The canonical JSON Schema is:

```text
contracts/schemas/common/model_calibration_dataset.v4.schema.json
```

The shared `nex_runtime` admission contract requires:

- schema `model_calibration_dataset.v4` and the frozen public dataset ID;
- exactly 100 scenario pairs, 200 packages, and 800 candidates;
- exactly one READY and one LOW_CONFIDENCE package per scenario;
- exact CALIBRATION/HOLDOUT, language, and domain scenario quotas;
- unique normalized query and candidate text;
- one author and a distinct independent reviewer for every scenario;
- approved near-duplicate review with no score-guided authoring or mechanical
  paraphrase;
- deterministic ordering and semantic digest generation.

The admitted manifest is bounded. It includes counts, IDs, and the semantic
digest, but excludes query text, candidate text, author references, and
reviewer references. Dataset v3 bytes and its existing admission behavior are
unchanged.

## Nested Fold Assignment

`nex_cx.retrieval_calibration_folds` implements the S20Q-M assignment
primitive:

```text
calibration scenarios = 80
outer folds = 5 x 16 validation scenarios
inner folds = 4 x 16 validation scenarios per outer training set
group key = scenario_id
seed = s136-v4-nested-cv-v1
```

Assignment first uses seeded domain/language strata and deterministic hash
tie-breaking, then applies deterministic cross-fold swaps to minimize marginal
domain and language imbalance without changing fold sizes. Every outer and
inner scenario partition is checked for exact, duplicate-free coverage.

The generated plan contains scenario IDs and stratum counts only. It does not
contain query or candidate text. HOLDOUT scenarios are counted for provenance
but never admitted into outer or inner folds, and the plan explicitly denies
holdout access and runtime activation.

## Failure Boundaries

Admission fails closed for:

- unknown schema, dataset ID, or fields;
- package, scenario, partition, language, or domain quota drift;
- duplicate or mismatched scenario pairs;
- missing, duplicate, self-reviewed, pending, score-guided, or mechanically
  paraphrased reviews;
- dataset/design binding or frozen assignment-configuration drift;
- invalid fold geometry or duplicate/incomplete fold partitions.

## Verification

Focused regression and coverage:

```text
57 passed
combined focused coverage = 99%
dataset v4 admission module = 99%
nested fold assignment module = 100%
ruff = PASS
git diff --check = PASS
```

Contract validation:

```text
contract_validation=pass
schemas=230 examples=291 negative_examples=245 openapi=10
```

NeX-CX Slice Gate:

```text
2,746 passed
statement coverage = 99.05% (minimum 95.00%)
branch coverage = 98.23% (minimum 94.00%)
nested fold assignment module = 100.00% statement / 100.00% branch
contract validation = 230 schemas / 291 examples /
                      245 negative examples / 10 OpenAPI documents
golden journey transition audit = PASS
demo-to-product dependency audit = PASS
```

No PostgreSQL or remote embedding, reranking, or generation provider was
required for this contract and assignment foundation.

## Explicit Exclusions

S20Q-N does not:

- author or freeze the final v4 dataset content or digest;
- execute calibration, profile selection, threshold fitting, or holdout;
- change the incumbent embedding or reranker revision;
- change any runtime retrieval policy or confidence threshold;
- add a database migration or persistence boundary.

## Handoff

The next corrective Slice should author the 100 scenario pairs under this
contract, complete independent review, admit the immutable dataset digest, and
materialize the deterministic fold plan without calling a provider:

`S20Q-O: Dataset v4 Authoring, Review, and Immutable Admission`
