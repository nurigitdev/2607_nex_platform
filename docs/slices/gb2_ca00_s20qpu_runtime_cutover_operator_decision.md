# GB2-CA00-S20Q-P-U Runtime Cutover Operator Decision

## Objective

S20Q-P-U consumes the corrected S20Q-P-T terminal receipt and records a
separate, integrity-bound operator decision about runtime cutover. It does not
repeat HOLDOUT, call a model provider, query a database, activate the candidate
runtime policy, or infer cutover approval from the shadow-canary PASS status.

## Source Audit

The admitted S20Q-P-T receipt is:

```text
receipt hash     = sha256:14dd0a0d052e58cb8fc6644d5e3db2200bd1febab7969bffa36c7633c4a8f180
document hash    = sha256:9e3bbd2bb2d82bf51fc594d6227dd7b77efb4a71ebabf8660474b5025ce48535
sample count     = 6
latency samples  = 6
provider failures= 0
p95 latency      = 38912.964 ms
disagreement     = 1/6, 16.6666666667%
```

The earlier receipt whose latency was incorrectly recorded as zero is not an
admitted input. It lacked both the terminal `latency_samples_complete` check
and the snapshot `latency_sample_count`. Its receipt/document identity also
differs from the exact source binding frozen by this Slice.

## Decision Boundary

The new product contract is implemented in
`services/nex-cx/nex_cx/retrieval_answer_support_cutover_decision.py`.
It provides:

- exact terminal receipt, policy, readiness manifest, runtime profile, and
  provider-binding verification;
- nested receipt and snapshot semantic-hash verification;
- mandatory complete latency telemetry and one-to-one provider-call/sample
  counts;
- an immutable operator decision bound to the admitted receipt and frozen
  design;
- fail-closed rejection of stale hashes, malformed telemetry, changed reason
  codes, or any activation/cutover approval bit;
- a metadata-only decision manifest with zero provider, database, and HOLDOUT
  access.

The minimum extended-shadow screening count is 30. This number is a minimum
operational sample boundary, not statistical production qualification. A
production p95 latency SLO remains deliberately `NOT_FROZEN`, so the Slice
cannot approve cutover even after the sample minimum is reached.

## Operator Decision

The protected decision execution produced:

```text
decision              = CUTOVER_DEFERRED_CONTINUE_SHADOW
operator decision hash= sha256:54896e582c88e59211d6311b087b25649a83099ad9c4e5c0396afb34f3706dcb
decision receipt hash = sha256:12d8794439ca80a0642132e87f6b37da2ae00080f7633a4f0aec97fbbb2c19a0
manifest hash         = sha256:d7612e54e3406c14c05ab8261b6d4f8fa132eec3fa3677069aa0bc25ae14dedb
runtime activation    = prohibited
production cutover    = prohibited
```

The decision reasons are:

1. `SHADOW_SAMPLE_COUNT_BELOW_MINIMUM`;
2. `PRODUCTION_LATENCY_SLO_NOT_FROZEN`;
3. `DISAGREEMENT_REQUIRES_EXTENDED_OBSERVATION`.

The current `CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY` remains the active
and rollback policy. The answer-support candidate remains shadow-only.

## Evidence

Protected local evidence is written under ignored `reports/live/` paths:

- `gb2_ca00_s20qpu_runtime_cutover_decision_receipt.json`, mode `0600`;
- `gb2_ca00_s20qpu_runtime_cutover_operator_decision.json`.

The decision receipt is one-shot. A default disabled smoke invocation does not
overwrite existing terminal evidence.

## Verification

Focused tests:

```text
15 passed
product decision contract statement/branch = 100% / 100%
protected decision runner statement/branch = 100% / 100%
```

NeX-CX Slice Gate:

```text
tests                         = 3,015 passed
statement coverage            = 99.16%
branch coverage               = 98.40%
new product contract coverage = 100% statement / 100% branch
new protected runner coverage = 100% statement / 100% branch
contract validation           = 230 schemas, 291 examples,
                                245 negative examples, 10 OpenAPI documents
golden transition audit       = pass
demo dependency audit         = pass
tiered Slice Gate             = 7/7 commands passed
```

## Next Boundary

`EXTENDED_SHADOW_OBSERVATION_AND_LATENCY_SLO_FREEZE`

That boundary must collect a larger, representative shadow sample, freeze a
production latency SLO independently from provider timeout and shadow stop
budgets, and review disagreement behavior. It must not reopen the one-shot
HOLDOUT or activate the candidate merely because S20Q-P-T and this decision
boundary passed.
