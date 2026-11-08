# GB2-CA00-S20Q-P-AB Limited Shadow Runtime Operations

## Outcome

`GB2-CA00-S20Q-P-AB` is complete. The P-AA controlled answer-support observer
can now operate for one immutable, restart-safe 12-provider-sample window. The
protected acceptance decision is:

```text
LIMITED_SHADOW_RUNTIME_OPERATIONS_ACCEPTED
```

The window remains shadow-only. `CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY`
continues to produce every authoritative user-visible decision. HOLDOUT access,
primary decision mutation, raw-text projection, and production cutover remain
prohibited.

## Limited Operations Policy

The admitted policy is packaged with NeX-CX and bound to the exact P-AA
activation bundle:

```text
policy id              = cx-answer-support-limited-shadow-operations-v1
policy hash            = sha256:f47aef621065761e4b04b082e61f95e750f9647e26fd0b3bf175d8ef40db5d82
activation bundle hash = sha256:6d5c631c9e18418ae2787d4053d06cdf87cc49a3cbc67aea6258b11f29893a06
window id              = s20qpab-limited-shadow-window-v1
provider sample cap    = 12
operator review floor  = 12
event scan cap         = 500
```

The canonical Compose profile enables the limited wrapper around the existing
controlled observer. The service default remains disabled outside that profile.
Policy integrity or activation-bundle drift fails closed before the wrapper is
installed.

## Runtime and Operations Boundary

No database migration or new table was added. The implementation reuses
`service_operational_events` for activation state, request progress, and
sanitized shadow outcomes. The provider sample count is reconstructed from
durable `REQUEST_COMPLETED` and `REQUEST_FAILED` events, so process restart does
not reopen an exhausted window.

In-process allocated slots and reservations protect the cap while a c4 wave is
in flight. Durable completions and allocated slots are merged with `max`, rather
than added, so a completion persisted just before reservation release is not
double-counted. Once the cap is reached, later requests return
`LIMITED_WINDOW_COMPLETE` without calling the provider. Telemetry persistence
remains best effort and cannot alter the retrieval response.

The protected NeX-AG operations route is:

```text
GET /internal/v1/retrieval/answer-support/shadow-operations
required caller = nex-ag
required scopes = service:call, operations:read
```

Its projection contains counts, latency percentiles, activation/rollback state,
window status, and runtime concurrency only. It contains no query, evidence,
credential, or provider response text.

## Protected Live Acceptance

The runner migrated and used the actual `nex_cx_test` PostgreSQL database and
the admitted Qwen3.5-9B generation deployment on port 9116. It issued three c4
waves, then verified the cap both immediately and after rebuilding the runtime.

```text
status                    = PASS
operations status         = REVIEW_REQUIRED
provider samples          = 12 / 12
provider calls            = 12
wave profile              = 3 waves x c4
peak in flight            = 4
elapsed                   = 32.773598 seconds
provider p95              = 10,987.585349 ms
end-to-end p95            = 11,012.279 ms
13th request              = provider blocked
restart request           = provider blocked
test DB residue           = 0 rows
evidence hash             = sha256:1a57b1194a2c01438fd14e7aa92b7fcb44d11da45af9ba1362c68dba2184ea92
```

Before the accepted run, protected admission correctly rejected a missing live
provider configuration, a configured provider revision that differed from the
immutable bundle, and a missing `NEX_CX_TEST_DATABASE_URL`. Each rejection
occurred with zero provider HTTP requests.

The ignored local evidence file is:

- `reports/live/gb2_ca00_s20qpab_limited_shadow_operations.json`.

The runner removed its deterministic activation, progress, and outcome rows.
A direct PostgreSQL query independently confirmed zero rows for the protected
trace ID.

## Verification

Focused verification before the final Slice Gate:

```text
focused boundary tests     = 17 passed
related CX regression      = 57 passed
product module coverage    = about 99% combined
protected runner coverage  = 100% statement / 100% branch
Ruff / py_compile          = pass
```

Final Slice Gate:

```text
NeX-CX regression          = 3,133 passed
statement coverage         = 99.21%
branch coverage            = 98.42%
product scope              = 99.60% statement / 94.74% branch
protected runner scope     = 100.00% statement / 100.00% branch
contract validation        = 230 schemas, 291 examples,
                             245 negative examples, 10 OpenAPI documents
golden transition audit    = pass
dependency audit           = pass
tiered Slice Gate          = 7/7 commands passed
```

The default-disabled smoke invocation returned `SKIPPED` and preserved the
terminal protected live evidence.

## Next Boundary

`LIMITED_SHADOW_OPERATOR_REVIEW_DECISION`

The next boundary may review this exact completed window and decide whether a
new observation window, continued shadow operation, or rollback is justified.
It must not rerun HOLDOUT or treat this acceptance as permission for a
user-visible policy replacement or production cutover.
