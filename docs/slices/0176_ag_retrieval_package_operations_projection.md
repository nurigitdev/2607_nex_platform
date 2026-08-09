# Slice 0176: AG Retrieval Package Operations Projection

## Scope

Slice 0176 adds an AG read-only operations projection for persisted CX
retrieval packages.

Implemented:

- `GET /admin/v1/operations/retrieval-packages`
- memory and SQLAlchemy-backed retrieval package operation stores
- PostgreSQL-compatible source wiring through the existing AG operations source
  runtime
- filters for status, trace id, request id, retrieval policy id, time range,
  sort, cursor, and limit
- safe summaries for package status, policy usage, low-confidence/no-answer
  counts, and evidence totals
- regression coverage for route auth, filter validation, source gaps, SQL read
  failures, and SQLite boolean compatibility

## Decision

AG reads CX retrieval package rows as operator/debug metadata only. It does not
return raw source text, evidence text, prompt text, storage paths, or vector
payloads. The projection exposes hashes, bounded query preview, status,
policy/ranker metadata, source counts, score summary values, and trace/request
correlation fields.

The endpoint follows the existing AG operations runtime contract:

- memory mode returns a default empty CX source
- postgres mode uses the selected `nex-cx` database URL for read-only
  projection
- unconfigured or unavailable sources are reported as degraded source statuses
  rather than failing the full projection

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ag_retrieval_operations.py tests/test_nex_ag_operations.py
```

Observed result:

```text
144 passed, 1 warning
```
