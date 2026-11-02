# GB2-CA00-S20Q-E: Dataset v3 Calibration Collection and Feature Diagnostics

## Status

`CLOSED`

## Outcome

S20Q-E collected calibration-only package evidence from the frozen v3 dataset
through the production NeX-CX hybrid retrieval path. It used the actual
`nex_cx_test` PostgreSQL database and the live embedding and reranking
providers. The v3 holdout was not sent to either provider and was not used in
feature statistics, weight selection, or threshold selection.

This Slice does not activate a runtime calibration profile. It adds a
diagnostic-only API that explicitly prohibits:

- holdout access;
- feature-weight selection;
- threshold selection;
- runtime activation.

## Collection Boundary

The admitted source remains:

```text
dataset id = s136-retrieval-package-confidence-public-v3
dataset sha256 = edde3040ef27adf2ae450cc3c2193a0900620e2e514dc372a31ebe57085b34fb
partition = CALIBRATION
scenario pairs = 20
packages = 40
candidates = 160
READY / LOW_CONFIDENCE = 20 / 20
```

Each package used one retrieval and reranking request over all four admitted
candidates. Candidate labels were not used to filter the retrieval scope.
The collector rejects incomplete candidate sets, non-contiguous ranks,
binding drift, and any provider payload containing a v3 holdout query or
candidate passage.

The live provider binding was:

```text
embedding revision = Qwen3-Embedding-4B
reranker revision = hf:22e683669bc0f0bd69640a1354a6d0aebcfeede5
ranking policy = weighted_rrf_vector_bm25_v1
chunk policy = chunk_1000_100
tokenizer policy = cx-tokenizer-profile:sha256:bea6a191e61ec9c45e5cafc3c973bfcca5fa1147872800b6bb27eb0cab03d7ab
```

Observed provider calls were 200 successful embedding requests and 40
successful reranking requests, with zero provider failures. The 200 embedding
requests comprise 160 candidate indexing calls and 40 package-query calls.

## Feature Diagnostics

The calibration-only result is:

| Feature | Classification | Higher-is-READY AUC | Paired READY higher / tie / lower |
| --- | --- | ---: | ---: |
| `reranker_score` | `DIRECTIONAL` | 0.6500 | 12 / 0 / 8 |
| `reranker_margin` | `NON_DISCRIMINATIVE` | 0.4825 | 9 / 0 / 11 |
| `rrf_normalized_score` | `INVERTED` | 0.4100 | 7 / 2 / 11 |
| `channel_support` | `CONSTANT` | 0.5000 | 0 / 20 / 0 |

Additional observations:

- `reranker_score` is directional but not sufficient by itself to justify an
  active package-confidence profile.
- `reranker_margin` does not separate the package labels in this corpus.
- `rrf_normalized_score` currently moves in the wrong direction for a
  higher-is-READY assumption.
- `channel_support` has one unique value because every top candidate was
  present in both retrieval channels; it contributes no discrimination.
- no near-perfect cross-feature correlation was observed among the
  non-constant features.

The diagnostic result is intentionally descriptive. No sign inversion,
feature drop, new weight, or threshold is encoded by S20Q-E.

## Persistence and Privacy

The protected run persisted 40 retrieval packages and 160 temporary content
objects in `nex_cx_test`, verified restart readback, and removed all temporary
rows afterward. PostgreSQL retained query hashes rather than query previews,
and each package persisted four evidence-lineage records.

The evidence contains numeric feature packages, model and policy binding,
sample identities, and semantic hashes only. It excludes query text,
candidate text, provider endpoints, credentials, and database credentials.

Local protected evidence:

```text
path = reports/live/gb2_ca00_s20qe_v3_calibration_collection.json
file sha256 = 36a94ba3daac47b99d6aeaed9e2b83fc06b3ce0ea38008e824730d40e95042b7
sample set hash = sha256:46e189024e42fe784e3133be8778455225d6d05857e96b1e8a2656b888c613ec
diagnostic hash = sha256:4a751a46ecead27941e23c6487e448e6a74c10fbac25d5db9a7ceabf6b01f7e1
```

The `reports/` tree remains intentionally ignored. This document records the
bounded result while the local evidence file remains available for detailed
inspection.

## Verification

Focused regression and coverage:

```text
tests = 40 passed
focused aggregate coverage = 96% with branch measurement enabled
feature diagnostics module coverage = 99%
mixed-package semantics statement/branch coverage = 100% / 100%
```

Protected live collection:

```text
status = PASS
actual PostgreSQL = nex_cx_user@nex_cx_test
calibration packages = 40
candidate documents = 160
embedding calls = 200 success / 0 failure
reranking calls = 40 success / 0 failure
holdout provider calls = 0
restart readback = PASS
zero-residue cleanup = PASS
```

NeX-CX Slice Gate:

```text
regression tests = 2,608 passed
statement coverage = 99.01% (minimum 95.00%)
branch coverage = 98.19% (minimum 94.00%)
contract validation = 229 schemas / 291 examples /
                      245 negative examples / 10 OpenAPI documents
golden journey transition audit = PASS
demo-to-product dependency audit = PASS
```

## Handoff

The next corrective Slice must not fit weights over the unchanged four
features as if S20Q-E had established adequate discriminativeness. It should
first review feature semantics and candidate-level diagnostics, then propose
model-independent replacement or transformed signals using calibration data
only. The v3 holdout must remain sealed until a candidate feature policy and
weights are frozen.

A recommended next boundary is:

`S20Q-F: Calibration Feature-Set Correction and Candidate-Level Diagnostics`
