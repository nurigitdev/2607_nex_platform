# GB2-CA00-S20Q-I: Candidate Relevance Signal Expansion

## Status

Complete. The expanded calibration decision is `NO_ACCEPTABLE_POLICY` and is
fail-closed. The S20Q holdout remains sealed, no policy is activated at
runtime, and the next admitted corrective work is a one-revision-at-a-time
reranker A/B Slice.

## Objective

S20Q-H proved that candidate membership, channel ranks, weighted RRF,
reranking, and final rank are repeatable on one fixed persisted corpus. It did
not find a policy satisfying both false-ready and READY-recall constraints
using only:

- `reranker_score`;
- `rrf_normalized_score`;
- `channel_rank_quality`.

S20Q-I evaluates additional relevance signals already present in retrieval
evidence before changing embedding or reranker models. It does not relax the
acceptance constraints and does not access the holdout partition.

## Source Audit

The production retrieval path preserves raw channel scores in each evidence
item:

- PostgreSQL BM25 emits a positive, corpus- and query-dependent score;
- pgvector emits cosine similarity as `1.0 - cosine_distance`;
- weighted RRF keeps raw channel scores, ranks, and normalized RRF quality;
- the authorized reranker replaces final ordering but retains channel scores.

Raw BM25 values therefore cannot be compared across packages without local
normalization. Cosine similarity has stable meaning but repeated live query
embedding calls introduce bounded numeric movement.

## Signal Contract

The historical three-signal projection remains available. S20Q-I adds an
explicit five-signal projection and a separate policy identifier:

```text
policy = cx_candidate_relevance_expanded_channel_scores_v1

historical signals:
  reranker_score
  rrf_normalized_score
  channel_rank_quality

added signals:
  bm25_score_quality
  vector_similarity_quality
```

Normalization is deterministic and label-free:

```text
bm25_score_quality = candidate BM25 / maximum BM25 in the same package
vector_similarity_quality = clamp(cosine similarity, 0.0, 1.0)
missing channel quality = 0.0
```

The projection rejects a rank/score presence mismatch. Relevance truth,
tenant identity, ownership, and permission decisions are not runtime
features. At most three of the five signals may be selected, preserving the
existing overfitting guard.

Candidate observation and expanded sample schemas were advanced to v2. The
historical three-signal relevance sample remains v1 and is not silently
reinterpreted.

## Numeric Repeatability

The first strict live run found that all ranks and reranker/RRF values were
exactly stable while repeated query embedding calls moved cosine similarity by
at most `0.00324517`. Treating vector similarity as exact at `1e-8` would have
been incorrect.

S20Q-I therefore admits a conservative `0.005` vector-similarity tolerance.
This tolerance is not merely used to pass the repeatability check: the
calibrator applies the weighted tolerance as an adverse margin to relevant and
non-relevant candidate scores. BM25 quality remains exact at `1e-8`; the
previous reranker tolerance remains `0.0005`.

Final five-repeat evidence:

```text
candidate membership changes = 0
BM25 rank / quality changes = 0 / 0
vector rank changes = 0
vector similarity drift above 0.005 = 0
maximum vector similarity delta = 0.00327087
RRF drift = 0
reranker drift = 0
final rank changes = 0
pipeline status = STABLE
```

## Protected Live Result

The protected run used:

- actual PostgreSQL `nex_cx_user@nex_cx_test`;
- 160 documents seeded once;
- 40 calibration packages queried five times;
- Qwen3-Embedding-4B through the live embedding provider;
- immutable Qwen3-Reranker-4B revision
  `hf:22e683669bc0f0bd69640a1354a6d0aebcfeede5`;
- 360 embedding and 200 reranking calls with no provider failure;
- zero holdout provider calls;
- restart-exact readback and complete cleanup.

Single-signal candidate AUC:

```text
reranker_score             = 0.83750000
channel_rank_quality       = 0.79937500
rrf_normalized_score       = 0.74937500
vector_similarity_quality  = 0.71375000
bm25_score_quality         = 0.67416667
```

Expanded search result:

```text
profiles evaluated = 455
admissible profiles = 0
status = NO_ACCEPTABLE_POLICY

best-effort signals = reranker_score,
                      channel_rank_quality,
                      bm25_score_quality
weights = 0.60 / 0.30 / 0.10
candidate AUC = 0.82604167
OOF balanced accuracy = 0.75
OOF false-ready rate = 0.15
OOF READY recall = 0.65
minimum fold balanced accuracy = 0.625
threshold spread = 0.00309085

required false-ready rate <= 0.10
required READY recall >= 0.80
```

The additional channel scores are informative but do not satisfy the unchanged
package-level safety constraints. Relaxing the threshold or opening holdout at
this point would invalidate the calibration protocol.

Local protected evidence:

```text
path = reports/live/gb2_ca00_s20qi_candidate_relevance_signal_expansion.json
file sha256 = f5a13e6567fb406cf40364b82eb20d1061fc69d8097c39739dfc134c928636a2
pipeline repeatability hash = sha256:ff8021f646eb29ff7a52ccdf960b78b6823b7c2524d316e491ed5a9f2e7af1b0
```

The ignored `reports/` artifact remains local. This document records its
reviewed bounded result.

## Verification

Focused regression:

```text
55 passed
ruff = PASS
```

NeX-CX Slice Gate:

```text
2,657 passed
statement coverage = 99.05% (minimum 95.00%)
branch coverage = 98.29% (minimum 94.00%)
new calibration/diagnostics/repeatability modules = 100% statement/branch
contract validation = 229 schemas / 291 examples /
                      245 negative examples / 10 OpenAPI documents
golden journey transition audit = PASS
demo-to-product dependency audit = PASS
```

## Closure Decision

S20Q-I is complete as a bounded signal-expansion and fail-closed calibration
Slice. It does not authorize runtime activation or the original S20Q holdout.

The next Slice should keep this dataset, constraints, five-repeat fixed-corpus
gate, and provider binding procedure unchanged while changing only the
reranker model revision. Embedding revision A/B remains deferred until the
reranker A/B result is known.
