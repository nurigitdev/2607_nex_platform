# GB2-CA00-S20Q-P-AH Answer-Support Policy Cutover Operations

## Outcome

`GB2-CA00-S20Q-P-AH` is complete. The P-AG answer-support policy cutover now
has a bounded, restart-safe operations window and a protected AG-facing
projection. The window observes the user-visible cutover policy without
rerunning HOLDOUT, changing candidate order, or authorizing a platform
production release.

The observation cap is an operator-review boundary. It does not stop the
authoritative retrieval runtime. Existing automatic fallback and rollback
behavior remains dominant.

## Immutable Operations Policy

The installed operations policy is:

```text
services/nex-cx/nex_cx/data/answer_support_policy_cutover_operations.v1.json
```

Its immutable bindings are:

```text
P-AG acceptance evidence = sha256:c07655bcba5fc85db6506bbcba873dbb33d3ed91fd2395cd266837df18545aac
authorization hash       = sha256:fe45b9267af3e81095b957c0488ee86dba7f88114b3fff99708ccc812108fc00
activation bundle hash   = sha256:6d5c631c9e18418ae2787d4053d06cdf87cc49a3cbc67aea6258b11f29893a06
selected policy hash     = sha256:c81f7a0bf3d3d72d7bbc5de1f564ada3b415f2206689c1939fcb925f172168cb
operations policy hash   = sha256:7f6dd67840bf1de1ba0d5b9f2d6c5d66afffba6e0ebc5bdb71620d2c7259e439
```

The policy permits 12 provider observations in three concurrency-four waves.
Operator review is required when the cap is reached. HOLDOUT access, raw-text
projection, and production cutover are prohibited.

## Runtime and Persistence

The controlled cutover emits a deterministic decision event for every
`APPLIED`, `FALLBACK`, or `SKIPPED` outcome. Events contain identifiers,
policy and package hashes, latency, and decision state, but no query or
candidate text. A sink failure cannot change the authoritative retrieval
result.

No migration or new table was added. The implementation reuses
`service_operational_events` with:

```text
cx.retrieval.answer_support_policy_decision
cx.retrieval.answer_support_policy_cutover_window
```

The window projection recovers after restart and exposes a protected
operations route:

```text
GET /internal/v1/retrieval/answer-support/policy-cutover-operations
```

The route requires the existing CX operations authorization and is intended
for AG operators. A terminal `ROLLED_BACK` or `ROLLBACK_PENDING_REVIEW` state
is projected without opening a new observation window.

## Protected Live Acceptance

The protected runner used the actual `nex_cx_test` PostgreSQL database and the
immutable Qwen3.5-9B provider profile. It made exactly 12 generation requests
in three concurrency-four waves.

```text
sample count              = 12
provider calls            = 12
peak in-flight            = 4
READY decisions           = 9
LOW_CONFIDENCE decisions  = 3
fallback or skipped       = 0
feedback p95              = 1.149283 ms
provider p95              = 11,340.367061 ms
end-to-end p95            = 11,422.5 ms
elapsed wall time         = 33.589883 s
restart recovery          = PASS
test DB residue           = 0 rows
operations status         = REVIEW_REQUIRED
```

All configured SLO checks passed. Permission scope, evidence identity and
order, and package lineage were preserved.

Ignored local evidence:

```text
reports/live/gb2_ca00_s20qpah_answer_support_policy_cutover_operations.json
semantic evidence hash = sha256:0c1ba91b7cf5b537db9f0b3cd24beef651372c2ef8f59aa1422a3048fac14827
file SHA-256          = f98c83d0aa80bffd28537d78eb3c095d02c1109e095d3e1da753fe411e4c38a8
```

## Verification

```text
focused tests              = 40 passed
focused implementation     = 99% coverage
focused and adjacent tests = 202 passed
canonical Compose audit    = PASS

NeX-CX Slice Gate          = 3,194 passed
statement coverage         = 99.23%
branch coverage            = 98.42%
contract validation        = 230 schemas, 291 examples,
                             245 negative examples, 10 OpenAPI documents
golden transition audit    = PASS
dependency audit           = PASS
tiered Slice Gate          = 5/5 commands passed
```

## Next Boundary

`ANSWER_SUPPORT_POLICY_CUTOVER_OPERATIONS_OPERATOR_REVIEW`

The next boundary may review this completed operations receipt and decide
whether the bounded cutover observations support continued controlled use.
It must not rerun HOLDOUT or reinterpret this Slice as a production release
authorization.
