# GB2-CA00-S20Q-J: Reranker Revision A/B

## Status

Complete. Both immutable reranker revisions were collected under the exact
same experiment binding. Neither satisfied the frozen calibration safety
constraints, so the decision is `NO_ADMISSIBLE_REVISION`. S20Q remains sealed,
no runtime calibration policy or model rollout is authorized, and the next
corrective step is controlled embedding revision A/B.

## Objective

S20Q-I proved that five existing relevance signals were informative but did
not satisfy the unchanged package-level safety constraints. S20Q-J changes
only the reranker revision while preserving:

- the admitted dataset v3 calibration partition;
- Qwen3-Embedding-4B and the seeded PostgreSQL corpus;
- chunk, tokenizer, ranking, feature, and cross-validation contracts;
- five-repeat full retrieval-pipeline measurement;
- maximum false-ready rate `0.10` and minimum READY recall `0.80`;
- the unopened S20Q holdout partition.

Historical 0.6B results are not comparable because they predate dataset v3
and the current feature package. Revision B must be measured again.

## Implementation

`retrieval_reranker_revision_ab.py` provides two bounded operations:

1. project a passed S20Q-I, direct repeatability, and immutable revision
   evidence set into an integrity-bound revision profile;
2. compare A and B only when every non-reranker experiment binding is exact.

The comparison rejects:

- mutable or equal artifact revisions;
- dataset, embedding, chunk, tokenizer, ranking, feature, or calibration drift;
- request-shape or score-semantics drift;
- tampered profile or nested experiment hashes;
- unstable pipelines, opened holdout evidence, or runtime-enabled policies.

Selection is safety-first. A revision must first produce `FROZEN`. When both
are admissible, lower false-ready rate precedes recall, fold stability,
balanced accuracy, candidate AUC, and threshold spread. Exact ties retain A.
When neither is admissible, the decision is `NO_ADMISSIBLE_REVISION`; the
better-looking rejected profile is not promoted.

The protected runner has explicit `PROFILE` and `COMPARE` modes. Its compare
mode admits the runner's canonical evidence envelope as well as the bounded
inner profile. It persists
only bounded metrics, immutable identities, evidence hashes, and decision
metadata. Provider endpoints, credentials, request text, and candidate rows
are excluded.

S20M-A's former Qwen3-4B-specific repeatability profile identifier is now
derived from the model/revision/deployment/request/dataset binding. Existing
evidence remains valid; new revision evidence no longer carries a misleading
4B identifier.

## Revision A Evidence

The existing S20Q-I evidence was admitted without another provider run because
it already uses the exact frozen contract required by S20Q-J:

```text
slot = A
served model = Qwen3-Reranker-4B
artifact revision = hf:22e683669bc0f0bd69640a1354a6d0aebcfeede5
dataset = s136-retrieval-package-confidence-public-v3
pipeline repeats = 5
direct observations = 600
pipeline status = STABLE
calibration status = NO_ACCEPTABLE_POLICY
false-ready rate = 0.15
READY recall = 0.65
candidate AUC = 0.82604167
holdout = SEALED
runtime activation = prohibited
```

Local protected evidence:

```text
path = reports/live/gb2_ca00_s20qj_reranker_revision_profile_a.json
file sha256 = eb91a5aab324e890e54e833914001f87cb9b651c35625eb35fc11a9677b71b46
profile hash = sha256:c448103009ae46db288d78e02e425d9e6719dcde69e185c462fe498a7eef1805
experiment binding hash = sha256:3e76dc0875191d1da1dd07f59007fe9475c1eda87757a7ff023269391b2b86a7
```

## Revision B Evidence

Revision B was served independently on the same DGX host. The B profile was
not inferred from historical 0.6B results; artifact evidence, direct numeric
repeatability, and the full dataset v3 pipeline were executed again.

```text
slot = B
served model = Qwen3-Reranker-0.6B
artifact revision = hf:e61197ed45024b0ed8a2d74b80b4d909f1255473
deployment = vllm-reranker-0-6b-s20qj-b
request shape = rerank
score semantics = provider_native_relevance_0_1
direct repeats / observations = 5 / 600
maximum direct score range = 0.0
cross-label rank exchanges = 0
pipeline repeats / candidate observations = 5 / 800
embedding / reranking successes = 360 / 200
provider failures = 0
maximum vector similarity delta = 0.00324488
pipeline status = STABLE
calibration status = NO_ACCEPTABLE_POLICY
holdout = SEALED
runtime activation = prohibited
PostgreSQL cleanup = complete
```

The B run used actual `nex_cx_user@nex_cx_test`, Qwen3-Embedding-4B on the
existing embedding provider, and Qwen3-Reranker-0.6B on the isolated B
provider. Dataset, embedding revision, chunk policy, tokenizer policy,
weighted-RRF policy, calibration contract, and experiment binding hash match A
exactly.

Local protected evidence hashes:

```text
artifact evidence = 3e63edda337f833b2920e83f393e9e94fba151e9a9445780acddfb0840a2f4fe
live binding = 34dd9ea2d2442bf18d921db2585d484fba17120f7994ee3d2a5f975a27238b04
direct repeatability = 207f077d88c91a7ad80135a6a53ccb9e50299580d80fcb30f33c90429719ebfa
pipeline calibration = 7270c8a77a3b5eb380df67bc86ddc339c2af75fccfd83d3fe67754c15167d0c3
bounded B profile = ce211d8e0af104c5c77ccc3622b7721d2200ccd5e37b9947ecd4351be9eabcf0
B profile hash = sha256:a09db689a89fc4c59a8c576b514b7f681181dd6bb97876e59772d6a7f7fb5be6
```

## A/B Decision

Both profiles have the same experiment binding hash:

```text
sha256:3e76dc0875191d1da1dd07f59007fe9475c1eda87757a7ff023269391b2b86a7
```

Calibration-only comparison:

| Metric | A: Qwen3-Reranker-4B | B: Qwen3-Reranker-0.6B | Required |
| --- | ---: | ---: | ---: |
| admissible profiles | 0 | 0 | at least 1 |
| false-ready rate | 0.15 | 0.15 | <= 0.10 |
| READY recall | 0.65 | 0.60 | >= 0.80 |
| balanced accuracy | 0.75 | 0.725 | - |
| minimum fold balanced accuracy | 0.625 | 0.375 | >= 0.50 |
| candidate AUC | 0.82604167 | 0.80916667 | >= 0.70 |
| threshold spread | 0.00309085 | 0.00142474 | <= 0.20 |

The 0.6B revision did not improve the failed safety dimensions. A is better on
recall, balanced accuracy, minimum fold stability, and candidate AUC, but A is
also rejected. Selecting A as a winner from rejected profiles would violate
the frozen admission contract.

```text
decision = NO_ADMISSIBLE_REVISION
selected slot = none
reason = CALIBRATION_CONSTRAINTS_NOT_SATISFIED
next action = CONTROLLED_EMBEDDING_REVISION_AB
holdout access = prohibited
runtime activation = prohibited
A/B evidence sha256 = 50f8429fffb6222e7e47b4697961bbc58d084b51c44f6f3447f9c1679a99ee46
```

## Verification

Focused unit and branch verification before final Slice Gate:

```text
26 passed
S20Q-I protected runner = 100% statement / 100% branch
new profile/comparison module = 100% statement / 100% branch
new protected runner = 100% statement / 100% branch
```

Revision A projection:

```text
gb2_s20qj_reranker_revision_ab=pass
mode=profile
slot=A
decision=NO_ACCEPTABLE_POLICY
```

Revision B and comparison:

```text
gb2_s20ma_numeric_repeatability=pass tolerance=0.0005 max_range=0.0
gb2_s20qi_signal_expansion=pass decision=NO_ACCEPTABLE_POLICY holdout=sealed
gb2_s20qj_reranker_revision_ab=pass mode=profile slot=B
gb2_s20qj_reranker_revision_ab=pass mode=compare decision=NO_ADMISSIBLE_REVISION
```

NeX-CX Slice Gate:

```text
2,683 passed
statement coverage = 99.08% (minimum 95.00%)
branch coverage = 98.33% (minimum 94.00%)
S20Q-I protected runner = 100% statement / 100% branch
new profile/comparison module = 100% statement / 100% branch
new protected runner = 100% statement / 100% branch
contract validation = 229 schemas / 291 examples /
                      245 negative examples / 10 OpenAPI documents
golden journey transition audit = PASS
demo-to-product dependency audit = PASS
```

## Closure Decision

S20Q-J is complete as a controlled negative A/B decision. Qwen3-Reranker-0.6B
must not replace the current canonical Qwen3-Reranker-4B, and neither revision
may activate the pending confidence policy. The original S20Q holdout remains
unopened. The next Slice should preserve this corpus, reranker A revision,
constraints, and feature contract while changing only the embedding revision.
