# Slice 0101: AG Operations Query Contract Hardening

## Scope

Slice 0101 hardens AG operations query behavior for the read-only operations
APIs:

- `GET /admin/v1/operations`
- `GET /admin/v1/operations/jobs`
- `GET /admin/v1/operations/events`

Added query contract fields:

- `since`: inclusive ISO-8601 lower time bound
- `until`: inclusive ISO-8601 upper time bound
- `sort`: `desc` or `asc`
- `cursor`: non-negative integer offset cursor
- `limit`: still clamped to the shared 500-row operations ceiling

## Timestamp Rule

Jobs use `updated_at` as the operation timestamp, falling back to `created_at`
when needed.

Events use `created_at` as the operation timestamp.

All query timestamps are normalized to UTC wire format with `Z`.

## Response Contract

Existing filters remain in place and are extended with normalized query
contract fields. Projections now include `pagination` metadata:

```json
{
  "limit": 50,
  "cursor": null,
  "returned": 10,
  "total_after_filters": 25,
  "next_cursor": "10"
}
```

Unified operations include separate job and event pagination blocks because the
two embedded projections are queried independently.

## Validation

Invalid sort values, negative or non-numeric cursors, invalid timestamps, and
inverted time windows return problem+json with AG-specific error codes.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py
```

Observed result:

```text
48 passed
```
