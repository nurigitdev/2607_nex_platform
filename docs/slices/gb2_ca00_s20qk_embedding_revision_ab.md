# GB2-CA00-S20Q-K: Embedding Revision A/B

## Status

Complete. Qwen3-Embedding-4B and Qwen3-Embedding-8B were measured against
the same dataset v3 calibration corpus, PostgreSQL state, Qwen3-Reranker-4B
revision, ranking policy, and five-repeat full retrieval pipeline. Both runs
were stable, but neither satisfied the frozen package-level safety
constraints. The decision is `NO_ADMISSIBLE_REVISION`; no embedding rollout,
holdout access, or runtime calibration activation is authorized.

## Objective

S20Q-J showed that changing the reranker revision alone did not satisfy the
unchanged false-ready and READY-recall constraints. S20Q-K changes only the
embedding artifact revision while preserving:

- dataset `s136-retrieval-package-confidence-public-v3` and its calibration
  partition;
- Qwen3-Reranker-4B revision
  `hf:22e683669bc0f0bd69640a1354a6d0aebcfeede5`;
- chunk, tokenizer, weighted-RRF, signal, and cross-validation contracts;
- five-repeat full retrieval-pipeline measurement;
- maximum false-ready rate `0.10` and minimum READY recall `0.80`;
- the unopened S20Q holdout partition.

The PostgreSQL vector columns are unconstrained `vector`, so the controlled
comparison can admit the 4B dimension `2560` and 8B dimension `4096`. Each
profile independently seeds, verifies restart readback, and cleans the same
test corpus. A vector dimension change is not treated as experiment drift;
all non-embedding bindings must remain exact.

## Implementation

`retrieval_embedding_revision_ab.py` provides bounded profile and comparison
operations. Profile admission requires:

- a passed S20Q-I full-pipeline evidence set;
- a stable five-repeat pipeline and completed calibration-only decision;
- immutable local Hugging Face artifact evidence;
- an exact live provider model revision and deployment response;
- a two-item OpenAI-compatible embedding probe with finite, consistent
  vectors;
- sealed holdout and prohibited runtime activation.

The profile persists only immutable identity, vector dimension, bounded
metrics, repeatability summaries, and evidence hashes. Provider endpoints,
credentials, probe text, vectors, raw queries, and candidate rows are not
persisted.

The comparison rejects tampered profiles, mutable or equal revisions,
dataset or policy drift, request-shape drift, and incomplete calibration.
Selection is safety-first. A revision must first produce `FROZEN`; metrics
from rejected profiles cannot authorize a winner.

## Immutable Artifact Binding

| Slot | Served model | Artifact revision | Dimension | Metadata | Weights | Manifest |
| --- | --- | --- | ---: | ---: | ---: | --- |
| A | Qwen3-Embedding-4B | `hf:5cf2132abc99cad020ac570b19d031efec650f2b` | 2560 | 13/13 | 2 | `sha256:8ab0fc61408a1390a030c02fc72f7d6fa2352601661f21abc7b4f67ac736fcc7` |
| B | Qwen3-Embedding-8B | `hf:1d8ad4ca9b3dd8059ad90a75d4983776a23d44af` | 4096 | 16/16 | 4 | `sha256:9aaeab8fdc85255fddf8afafce681838b1e46b32f6a4708c87c3992fd624023a` |

Both artifact inspections were produced on the DGX from local model
metadata. Model paths and artifact contents are excluded from repository
evidence.

## Protected Live Evidence

Each slot used actual `nex_cx_test`, 160 seeded documents, 40 retrieval
packages, 20 scenarios, 5 pipeline repeats, 800 candidate observations, 360
embedding calls, and 200 reranking calls. Both providers completed with zero
failure. PostgreSQL identity, migration state, restart readback, cleanup, and
holdout sealing all passed.

| Metric | A: Embedding-4B | B: Embedding-8B | Required |
| --- | ---: | ---: | ---: |
| calibration status | `NO_ACCEPTABLE_POLICY` | `NO_ACCEPTABLE_POLICY` | `FROZEN` |
| false-ready rate | 0.15 | 0.15 | <= 0.10 |
| READY recall | 0.60 | 0.55 | >= 0.80 |
| balanced accuracy | 0.725 | 0.70 | - |
| minimum fold balanced accuracy | 0.375 | 0.50 | >= 0.50 |
| candidate AUC | 0.80354167 | 0.826875 | >= 0.70 |
| threshold spread | 0.00087771 | 0.00217539 | <= 0.20 |
| maximum vector similarity delta | 0.0033736 | 0.0031713 | <= 0.005 |
| vector rank changes | 0 | 0 | 0 |

The 8B revision improved candidate AUC and minimum-fold accuracy, but did not
improve false-ready safety and reduced READY recall. Model size alone is not
an admission criterion.

## Decision

```text
decision = NO_ADMISSIBLE_REVISION
selected slot = none
reason = CALIBRATION_CONSTRAINTS_NOT_SATISFIED
next action = CALIBRATION_DATASET_AND_RELEVANCE_POLICY_REVIEW
holdout access = prohibited
runtime activation = prohibited
experiment binding hash = sha256:52941e51c2eb1d713a57a38d064c97598a86d33babdf29c4d5eacb297abf015b
comparison hash = sha256:1758af538db269dcb9c7023c1ed97ce202839c1eb565fca24b9aed19c6ec9d00
```

Protected local evidence hashes:

```text
A artifact evidence = 4e251ebd674035f12819672c4d776b40b8d301619015ab31809912e7b15a71a8
B artifact evidence = 5b94f980160ddb7c12fda7f8933eb339acf89821aca6421e268de97f9c0ae7f1
A pipeline evidence = c669a4a0e673f185f5352bb742fb063b1855923ba91bc11f5ff83f9bad30db73
B pipeline evidence = 44ae12c6793ecbbf6de98d57d5b2e6b372abf3ae4425956b9d712ebb1b95b967
A bounded profile = 9d3320e58da5df86568988f7d013265317c507076d4b5fdd6c6db69d8c57a7a6
B bounded profile = 0d60e8d9e2c2b8eb0f7ae1cb4a96227a265eef1805bca5f40140340d170e46bb
A/B comparison = 460f335751464088cb0ec2a9591c003fa6f5f6a73ec45ab79d08783b2e532e26
A profile hash = sha256:4e9b9fa089132ab37880505e0a83d01851141fca7f367296c5bd9e425d09634c
B profile hash = sha256:543ee7fb10a296473b23e3ec53d03b38591abb89d6192c5139398277cfe8fd6f
```

## Verification

NeX-CX Slice Gate:

```text
2,687 passed
statement coverage = 99.07% (minimum 95.00%)
branch coverage = 98.32% (minimum 94.00%)
profile/comparison module = 99.29% statement / 97.62% branch
protected runner = 100.00% statement / 100.00% branch
contract validation = 229 schemas / 291 examples /
                      245 negative examples / 10 OpenAPI documents
golden journey transition audit = PASS
demo-to-product dependency audit = PASS
```

Protected execution:

```text
gb2_s20qi_signal_expansion=pass decision=NO_ACCEPTABLE_POLICY holdout=sealed
gb2_s20qk_embedding_revision_ab=pass mode=profile slot=A dimension=2560
gb2_s20qk_embedding_revision_ab=pass mode=profile slot=B dimension=4096
gb2_s20qk_embedding_revision_ab=pass mode=compare decision=NO_ADMISSIBLE_REVISION
```

## Closure Decision

S20Q-K is complete as a controlled negative A/B decision. Qwen3-Embedding-8B
must not replace the current Qwen3-Embedding-4B from these results, and no
tested embedding revision may activate the pending confidence policy. The
original S20Q holdout remains unopened. The next corrective work should
review dataset and package-level relevance-policy semantics without relaxing
the frozen safety constraints merely to admit a larger model.
