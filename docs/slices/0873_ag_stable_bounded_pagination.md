# Slice 0873: AG stable bounded pagination

## Goal

Add stable, bounded keyset pagination to the S87 audit-integrity action read
model without changing source ownership or exposing raw audit data.

## Implementation

- Added a reusable keyset page builder to `nex_ag.resilience_performance`.
- Cursor order is `(created_at, event_id)` and defaults to descending order.
- The opaque base64url cursor contains only cursor version, sort direction,
  timestamp, and event ID.
- Newer inserts do not shift a previously issued cursor, avoiding the duplicate
  and skipped-row behavior of offset pagination.
- Malformed source rows are omitted and counted rather than crashing the read
  model.
- The audit-integrity operations route accepts `cursor` and returns
  `action_pagination` while preserving the existing `recent_limit` parameter.
- Invalid cursors return a redacted retry-safe `400` problem response without
  echoing cursor contents.
- Endpoint pages remain capped at 50 actions; the common S88 hard cap remains
  500 for other bounded query surfaces.

No table or migration was introduced.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_ag_resilience_performance.py \
  tests/test_nex_ag_audit_evidence_operations.py \
  --cov=nex_ag.resilience_performance \
  --cov=nex_ag.audit_evidence_operations \
  --cov=nex_ag.audit_evidence_api \
  --cov-branch --cov-report=term-missing
```

Observed verification:

```text
pagination policy tests: 31 passed, module statement/branch coverage 100%
focused pagination/operations tests: 39 passed
contract validation: schemas=79 examples=129 negative_examples=92 openapi=7
aggregate regression: 5947 passed, 1 known warning
statement=73024/73905=98.807929098167%
branch=17134/17784=96.345029239766%
```
