# GB2-CA00-S20Q-F: Feature-Set Correction and Candidate-Level Diagnostics

## Status

`CLOSED`

## Outcome

S20Q-F inspected the v3 calibration retrieval at candidate level and evaluated
runtime-observable replacement feature candidates. The v3 holdout remained
sealed. This Slice did not select features, fit weights, select a threshold,
or activate a runtime profile.

The source audit confirmed that the existing v2 confidence package projects
four values from the top-ranked candidate. That projection loses useful
distribution information, while `channel_support` becomes structurally
constant when all four admitted candidates appear in both retrieval channels.

S20Q-F therefore adds a diagnostic-only boundary that:

- preserves the existing v2 runtime feature package and sample hash contract;
- projects text-free, integrity-bound candidate observations separately;
- measures candidate relevance ranking without using relevance truth as a
  runtime feature;
- compares the current top-candidate fields with eight model-independent
  corrected package feature candidates;
- defers feature selection to `GB2-CA00-S20Q-G`.

No database migration or public runtime API change was made.

## Diagnostic Feature Boundary

The current package fields were restated as:

```text
reranker_top_score
reranker_top_margin
rrf_top_score
top_channel_support
```

The corrected candidate fields are:

```text
reranker_top2_mean
reranker_second_score
reranker_top2_tail_gap
reranker_score_spread
rrf_top2_mean
top2_channel_rank_quality
reranker_rrf_order_agreement
lexical_vector_rank_agreement
```

All fields are derived only from admitted numeric retrieval evidence. Tenant,
owner, permission, candidate role, and expected relevance are excluded from
runtime feature values. Candidate truth is used only to evaluate the
calibration partition and is not included in the aggregate evidence.

## Protected Live Result

The protected run used the actual `nex_cx_test` PostgreSQL database and the
live DGX embedding and reranking providers:

```text
dataset                         = s136-retrieval-package-confidence-public-v3
dataset sha256                  = edde3040ef27adf2ae450cc3c2193a0900620e2e514dc372a31ebe57085b34fb
partition                       = CALIBRATION
packages / candidate rows       = 40 / 160
embedding calls                 = 200 success / 0 failure
reranking calls                 = 40 success / 0 failure
holdout provider calls          = 0
PostgreSQL restart readback     = PASS
zero-residue cleanup            = PASS
```

The immutable binding was:

```text
embedding revision = Qwen3-Embedding-4B
reranker revision  = hf:22e683669bc0f0bd69640a1354a6d0aebcfeede5
ranking policy     = weighted_rrf_vector_bm25_v1
chunk policy       = chunk_1000_100
tokenizer policy   = cx-tokenizer-profile:sha256:bea6a191e61ec9c45e5cafc3c973bfcca5fa1147872800b6bb27eb0cab03d7ab
```

## Candidate-Level Findings

The reranker ranks individual relevant candidates substantially better than
non-relevant candidates, but this does not by itself establish a sufficiently
separable package-confidence policy.

| Candidate signal | Higher-is-relevant AUC | Classification |
| --- | ---: | --- |
| `reranker_score` | 0.8329 | `DIRECTIONAL` |
| `channel_rank_quality` | 0.7998 | `DIRECTIONAL` |
| `rrf_normalized_score` | 0.7490 | `DIRECTIONAL` |

READY-package ranking diagnostics were:

```text
top-1 relevant rate                 = 0.9500
top-2 relevant recall               = 0.9000
mean reciprocal relevant rank       = 0.9750
```

## Package Feature Findings

Three corrected fields were directional in this calibration execution:

| Corrected field | Higher-is-READY AUC | Paired READY higher / lower |
| --- | ---: | ---: |
| `reranker_top2_mean` | 0.6775 | 13 / 7 |
| `reranker_second_score` | 0.6775 | 14 / 6 |
| `reranker_score_spread` | 0.6625 | 13 / 7 |

The remaining corrected fields are not eligible for positive-oriented weight
selection under this evidence:

| Corrected field | AUC | Finding |
| --- | ---: | --- |
| `reranker_top2_tail_gap` | 0.5300 | `NON_DISCRIMINATIVE` |
| `reranker_rrf_order_agreement` | 0.4550 | `NON_DISCRIMINATIVE` |
| `rrf_top2_mean` | 0.3425 | `INVERTED` |
| `top2_channel_rank_quality` | 0.4175 | `INVERTED` |
| `lexical_vector_rank_agreement` | 0.1600 | `INVERTED` |

For comparison, the current top-score and top-margin restatements were
directional at 0.6900 and 0.6350 AUC. `rrf_top_score` remained inverted and
`top_channel_support` remained constant.

The prior and current live executions show that marginal univariate values can
move across repeated provider executions. S20Q-G must therefore retain the
numeric repeatability constraints established by S20M-A and must not admit a
feature solely because one execution crossed the directional boundary.

## Safety Boundary

The diagnostic result explicitly records:

```text
runtime activation permitted = false
feature selection permitted  = false
weight selection permitted   = false
threshold selection permitted = false
holdout access permitted     = false
```

The evidence excludes query text, candidate text, provider endpoints,
credentials, and database credentials. PostgreSQL persisted query hashes and
retrieval lineage only, and all temporary documents, vector rows, source rows,
and retrieval packages were removed after restart readback.

Local protected evidence:

```text
path = reports/live/gb2_ca00_s20qf_candidate_feature_diagnostics.json
file sha256 = 865d44eb594c2feec897d5a7821b265abdf75ad54f613772d0088d465037d76b
sample set hash = sha256:3379cd9ba494ff13a453ef529e9d35bee86c2f913bd49bc9506512a6ff2b4176
diagnostic hash = sha256:5cc077890f06bad265adfbceb5cf095f0a829a3683188fac3e704312133e6b86
```

The ignored `reports/` evidence remains local; this document records the
reviewed bounded result.

## Verification

Focused diagnostics and runner regression:

```text
tests = 28 passed
candidate diagnostics statement/branch coverage = 100% / 100%
S20Q-F protected runner coverage = 99%
```

NeX-CX Slice Gate:

```text
regression tests = 2,629 passed
statement coverage = 99.02% (minimum 95.00%)
branch coverage = 98.22% (minimum 94.00%)
contract validation = 229 schemas / 291 examples /
                      245 negative examples / 10 OpenAPI documents
golden journey transition audit = PASS
demo-to-product dependency audit = PASS
```

## Handoff

The next Slice should be:

`S20Q-G: Calibration-Only Feature Selection, Weighting, and Threshold Freeze`

S20Q-G may compare the directional current fields and the three directional
corrected candidates, but it must use calibration data only, preserve grouped
scenario evaluation and repeatability constraints, and freeze one immutable
candidate policy before the original S20Q opens the holdout exactly once.
