# P7-CA02A: PostgreSQL Replay and Evidence Closure

## Status

Completed on 2026-10-19. This Slice changes no production runtime semantics.

## Closed Gaps

1. The protected WC PostgreSQL test now reconstructs the repository and reads
   all three create-authorization evidence fields after restart.
2. The same test executes a different authorized requester replay through the
   PostgreSQL `INSERT ... ON CONFLICT` path and requires non-retryable `409`, a
   single WorkItem row, and preservation of the original requester.
3. CA02 negative and Golden B evidence now distinguish the tested runtime
   revision, tested Git tree digest, and final CA02 closure commit.

## Actual PostgreSQL Evidence

```text
database / role          = nex_wc_test / nex_wc_user
migration head           = 1003_wc_work_item_authorization
protected test           = 1 passed, 0 skipped
authorization reads      = 4
restart evidence fields  = 3 / 3 preserved
wrong requester replay   = 409, retryable=false
WorkItem rows afterward  = 1, requester=original
owned residue            = 0
```

The authorization source is a deterministic test double because this Slice
targets WC persistence/replay semantics, not the already accepted OA HTTP
boundary. No remote provider is required.

## Provenance

```text
source revision = 67a47f91f0c7c77e816f18c8d3939d3450968b09
tested tree     = cee757fed13b5d2c2be14536763b75d79b325648
```

Sanitized evidence is stored in
`reports/live/p7-ca02a-postgres-replay-evidence.json`.

## Regression and Full Gate

```text
affected P7 regression = 199 passed, 5 skipped
repository Full Gate   = 15,407 passed, 48 skipped
statement coverage     = 96.83% (required 95%)
branch coverage        = 96.22% (required 85%; P7 policy 94% also satisfied)
contract validation    = 174 schemas, 236 examples, 204 negative, 8 OpenAPI
AE Web tests           = 331 passed, 0 failed
```

Protected external-dependency tests skipped by the default Full Gate retain
their existing opt-in behavior. The CA02A PostgreSQL test was enabled
explicitly against `nex_wc_test` and did not skip.
