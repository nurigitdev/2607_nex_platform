# GB2-CA00-S20Q-H: Full Retrieval-Pipeline Repeatability and Candidate-Relevance Calibration

## Status

`STOPPED_FAIL_CLOSED`

The full retrieval pipeline is repeatable on one immutable seeded corpus, but
the current runtime-available relevance signals do not satisfy the frozen
package safety constraints. No confidence policy was frozen, the v3 holdout
remains sealed, and runtime activation is prohibited.

## Scope

S20Q-H separates two questions that earlier evidence could not distinguish:

1. whether repeated full retrieval requests drift before or during reranking;
2. whether stable candidate-level signals are sufficiently discriminative for
   package readiness.

The Slice does not weaken labels, thresholds, or grouped validation. It does
not open the holdout, change the active retrieval policy, or bind platform code
to a specific model name.

## Implementation

### Seed-once repeated collection

The protected S20Q-E collector now supports a bounded repeat count. It creates
the 160 calibration documents and vector indexes once, then executes the same
40 mixed-candidate retrieval packages repeatedly against that fixed corpus.
The default remains one execution, preserving all S20Q-E through S20Q-G
callers.

Each repeat exports integrity-bound, text-free candidate observations keyed by
the dataset's semantic candidate identity rather than generated document UUID.
Query text, candidate text, endpoint, credential, and database secret values
are excluded.

### Full-pipeline repeatability

`retrieval_pipeline_repeatability.py` compares, in pipeline order:

- candidate membership;
- BM25 rank;
- vector rank;
- normalized RRF score;
- reranker score under the admitted S20M-A `0.0005` tolerance;
- final rank.

Any missing candidate, rank movement, score drift beyond tolerance, malformed
observation, replay, or integrity failure stops admission.

### Candidate relevance calibration

`retrieval_candidate_relevance_calibration.py` searches calibration-only
weights over the runtime-available candidate signals:

- `reranker_score`;
- `rrf_normalized_score`;
- `channel_rank_quality`.

Package confidence is the second-highest candidate score. This directly means
that a READY package requires at least two relevant evidence candidates, which
matches the v3 positive-package contract. Selection uses five-fold
scenario-grouped cross-validation and the unchanged constraints:

```text
false-ready rate <= 0.10
READY recall     >= 0.80
```

Candidate truth is used only in offline calibration and is never a runtime
feature. Even an admissible profile would remain a non-active candidate until
the untouched holdout passes.

## Protected Result

Execution environment:

```text
PostgreSQL = nex_cx_user@nex_cx_test
seeded documents = 160, created once
retrieval packages per repeat = 40
repeat count = 5
candidate observations = 800
embedding provider calls = 360, failures = 0
reranking provider calls = 200, failures = 0
holdout provider calls = 0
reranker artifact revision = hf:22e683669bc0f0bd69640a1354a6d0aebcfeede5
restart readback = PASS
zero-residue cleanup = PASS
```

Full-pipeline repeatability:

```text
status = STABLE
candidate membership changes = 0
BM25 rank changes = 0
vector rank changes = 0
RRF score drift count / max delta = 0 / 0.0
reranker score drift count / max delta = 0 / 0.0
final rank changes = 0
candidate comparisons = 640
```

Candidate-relevance search:

```text
profiles evaluated = 66
admissible profiles = 0
status = NO_ACCEPTABLE_POLICY

best-effort signals = reranker_score,
                      rrf_normalized_score,
                      channel_rank_quality
weights = 0.30 / 0.40 / 0.30
candidate AUC = 0.79916667
OOF balanced accuracy = 0.70
OOF false-ready rate = 0.15
OOF READY recall = 0.55
minimum fold balanced accuracy = 0.375
required false-ready rate <= 0.10
required READY recall >= 0.80
```

Local protected evidence:

```text
path = reports/live/gb2_ca00_s20qh_pipeline_repeatability_relevance.json
file sha256 = 071f674d994e9d5a8597d3ede67460410d0632a2e1a458e96e24f303c0d26571
pipeline repeatability hash = sha256:c1e21bd27de8afca454dd92da888aa84def19ae1baf2f6b9df63f0a6d75b397d
```

The ignored `reports/` artifact remains local. This document records its
reviewed bounded result.

## Interpretation

The prior cross-execution movement was not reproduced when the same persisted
corpus was queried five times. That movement was therefore attributable to the
old measurement method recreating UUID-backed documents between executions,
not to nondeterminism in the live fixed-corpus retrieval path.

The remaining failure is discriminative. A stable threshold cannot provide
both low false acceptance and sufficient READY recall with the current three
candidate signals. Threshold relaxation would violate the frozen safety
contract, and opening the holdout would leak the final acceptance partition
without a frozen candidate policy.

This evidence does not by itself prove that model size is the only limiting
factor. The next separately reviewed corrective work should compare, on the
calibration partition only:

1. additional runtime-available candidate relevance signals, including
   properly normalized channel scores rather than ranks alone;
2. one-at-a-time embedding and reranker model/revision A/B profiles;
3. the same five-repeat fixed-corpus and grouped-calibration gates.

Only a profile satisfying the unchanged constraints may authorize the original
S20Q holdout acceptance.

## Verification

Focused implementation regression:

```text
tests = 50 passed
new evaluator/runner statement and branch coverage = approximately 99%
ruff = PASS
```

NeX-CX Slice Gate:

```text
regression tests = 2,648 passed
statement coverage = 99.03% (minimum 95.00%)
branch coverage = 98.21% (minimum 94.00%)
contract validation = 229 schemas / 291 examples /
                      245 negative examples / 10 OpenAPI documents
golden journey transition audit = PASS
demo-to-product dependency audit = PASS
```

## Stop Decision

S20Q-H is complete as a fail-closed diagnostic and calibration Slice. The
original S20Q must not resume, and the current profile must not be activated.
A new corrective Slice requires explicit review before feature expansion or
model A/B execution.
