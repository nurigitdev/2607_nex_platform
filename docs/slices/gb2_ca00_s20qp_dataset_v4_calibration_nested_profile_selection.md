# GB2-CA00-S20Q-P: Dataset v4 Calibration Collection and Nested Profile Selection

## Status

Complete. The immutable dataset v4 CALIBRATION partition was collected through
the actual CX PostgreSQL, embedding, hybrid retrieval, and reranking path. The
frozen four-profile nested selection protocol completed with a valid
fail-closed result: `NO_ADMISSIBLE_PROFILE`.

The 20-scenario HOLDOUT partition remains sealed. No profile, threshold, or
runtime policy was activated.

## Objective

S20Q-O admitted 100 independently reviewed scenario pairs and froze 80 for
calibration and 20 for holdout. This Slice:

1. collects only the 160 calibration packages and 640 candidates;
2. repeats the full retrieval pipeline five times on one seeded corpus;
3. evaluates only the four S20Q-M profiles with the frozen 5x4 nested folds;
4. selects profile and threshold only in inner calibration folds;
5. evaluates the frozen inner selection on unseen outer folds;
6. opens no holdout score and permits no runtime activation.

## Implementation

### Reusable protected collector

`run_gb2_s20qe_v3_calibration_collection.py` now accepts a bounded immutable
dataset specification. The original v3 defaults and behavior remain unchanged,
while S20Q-P reuses the same PostgreSQL seeding, actual MO provider calls,
retrieval package persistence, restart readback, redaction, and cleanup path for
v4. The refactoring avoids a second copy of the large protected collector.

### Nested selector

`retrieval_calibration_nested_selection.py` implements the frozen S20Q-M
protocol:

- scenario-pair grouping prevents positive/negative leakage;
- the stored stratified 5x4 fold assignment is consumed without reassignment;
- candidate scores use only frozen profile features and weights;
- package confidence is the second-highest candidate score;
- each inner loop fits only a threshold and profile ID;
- the outer loop performs no profile or threshold reselection;
- candidate AUC is computed from candidate relevance labels for calibration
  diagnostics only;
- Wilson 95% intervals are reported while point constraints remain
  authoritative;
- fewer than four matching outer selections or any metric failure yields
  `NO_ADMISSIBLE_PROFILE`.

### Protected runner

`run_gb2_s20qp_v4_nested_calibration.py` binds the incumbent providers to the
previously extracted immutable artifact revisions:

```text
embedding = hf:5cf2132abc99cad020ac570b19d031efec650f2b
reranker  = hf:22e683669bc0f0bd69640a1354a6d0aebcfeede5
```

It verifies the frozen dataset and fold digests before provider execution,
guards every outbound provider payload against holdout query/candidate text,
and rejects evidence containing dataset text, endpoint credentials, database
credentials, or provider API keys.

## Live Evidence

The protected execution used the actual `nex_cx_test` database and the live
Qwen3-Embedding-4B and Qwen3-Reranker-4B providers.

```text
calibration scenarios = 80
calibration packages = 160
calibration candidates = 640
pipeline repeats = 5
embedding calls = 1,440
reranking calls = 800
provider failures = 0
holdout provider payload blocks = 0
pipeline repeatability = UNSTABLE
cleanup = PASS
```

Across all five repeats, candidate membership, BM25 rank, reranker score, and
final rank changes were zero. Eight vector-rank comparisons changed and caused
eight RRF score drifts; maximum RRF delta was `0.01129032`. Maximum vector
similarity quality delta was `0.00326445`, inside its existing tolerance. The
authoritative repeatability result is therefore `UNSTABLE`, with
`VECTOR_RANK` as the first unstable stage. No tolerance was relaxed.

The local evidence artifact is:

`reports/live/gb2_ca00_s20qp_v4_nested_calibration.json`

It contains numeric/hash evidence only and is intentionally not a runtime
configuration artifact.

## Nested Selection Result

Calibration admission was rejected for two independent reasons:

1. five-run full-pipeline repeatability was unstable at vector-rank/RRF stage;
2. no frozen profile satisfied the package-level false-ready and READY-recall
   constraints in every inner selection.

Candidate discrimination itself was meaningful: observed profile/fold
candidate AUC values ranged from `0.72070312` through `0.75718180`, above the
frozen `0.70` floor. The profile rejection occurred when candidate scores were
reduced to the second-highest package confidence:

- conservative thresholds kept false-ready near or below `0.10` but produced
  very low READY recall;
- permissive thresholds improved recall but exceeded the `0.10` false-ready
  limit;
- no profile was admitted by any outer fold, so outer OOF evaluation and final
  80-scenario threshold fitting were correctly withheld.

This is a protocol/execution success and an admission rejection. The runner
records those states separately. Best-effort metrics do not authorize holdout
access.

## Verification

Focused selector, runner, and collector regression:

```text
19 passed
nested selector = 100% statement / 100% branch
runner plus selector = 100% statement / 99% branch
ruff = PASS
```

NeX-CX Slice Gate:

```text
2,746 passed
statement coverage = 99.07% (minimum 95.00%)
branch coverage = 98.26% (minimum 94.00%)
S20Q-P runner = 100% statement / 100% branch
contract validation = 230 schemas / 291 examples /
                      245 negative examples / 10 OpenAPI documents
golden journey transition audit = PASS
demo-to-product dependency audit = PASS
```

## Safety Boundary

S20Q-P does not:

- score or inspect holdout results;
- choose a new model revision;
- add, remove, or change a frozen profile or feature weight;
- relax false-ready, recall, AUC, fold-accuracy, or spread constraints;
- activate a calibration profile or runtime threshold;
- add a database migration or persistent calibration table;
- retain calibration corpus rows after the protected smoke completes.

## Handoff

S20Q holdout acceptance must not resume from this result. The next corrective
decision should address both vector tie/rank repeatability and package-level
READY semantics, or introduce a separately reviewed package relevance signal.
Re-running the same four profiles or opening the holdout would not resolve the
observed calibration rejection.
