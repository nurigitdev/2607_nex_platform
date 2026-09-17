# Slice 0819: AG dispatch liveness acknowledgement expiry privacy/runbook

## Objective

Close the S82 privacy, concurrency, and operator-response evidence gap for
acknowledgement expiry reconciliation.

## Evidence

- Executes the protected reconciliation API against an in-memory persisted
  state and verifies one bounded `SUPPRESSED -> EXPIRED` transition.
- Verifies a second execution is a successful zero-candidate no-op.
- Forces a compare-and-set conflict and verifies it is reported without
  overwriting a concurrent state change.
- Exercises and records safe `400` and `503` problem responses.
- Verifies audit events expose aggregate counts and redaction flags, never raw
  comments, idempotency keys, credentials, provider keys, or database URLs.
- Rechecks static/runtime OpenAPI, the short table/index identifiers, required
  S82 evidence documents, and quality-gate wiring.

## Operator Runbook

| Signal | Response |
| --- | --- |
| `400` | Correct `observed_at` or `limit`, then retry once. |
| `401` | Refresh the NeX-OA service claim before retrying. |
| `503` | Inspect database health, migration status, and connection pool before retrying. |
| CAS conflict | Reload the acknowledgement state and preserve any concurrent renewal. |
| Zero-candidate rerun | Treat it as a successful idempotent no-op. |

## Verification

```bash
./.venv/bin/python scripts/smoke/run_ag_dispatch_liveness_ack_expiry_privacy_runbook_evidence.py --summary
./.venv/bin/pytest tests/test_ag_dispatch_liveness_ack_expiry_privacy_runbook_evidence.py -q --tb=short
```

Evidence result:
`ag_dispatch_liveness_ack_expiry_privacy_runbook=pass surfaces=10 privacy=True conflict=True runbook=True`.

Focused regression result: `15 passed, 1 warning`.

Full regression result: `5404 passed, 1 warning`.

- Statement coverage: `69215 / 70098 = 98.740334959628%`.
- Branch coverage: `16403 / 17054 = 96.182713732849%`.
- New evidence runner statement/branch coverage: `100% / 100%`.
