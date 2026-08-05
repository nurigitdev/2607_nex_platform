# Slice 0103: AG Operational Event Detail Search

## Scope

Slice 0103 extends the AG operational event projection with two operator
inspection tools:

- `GET /admin/v1/operations/events?q=...` for bounded text search across safe
  event fields.
- `GET /admin/v1/operations/events/{event_id}` for a single event detail view.

## Search Contract

The `q` filter is optional, whitespace-trimmed, and limited to 128 characters.
Blank values are treated as omitted. Invalid values return problem+json with
`ag.operation_event_query_invalid`.

Search runs against redacted projection data only:

- event id
- service id
- event type
- severity
- message
- trace id
- request id
- subject ref values
- redacted details JSON

The existing `since`, `until`, `sort`, `cursor`, and `limit` query behavior
continues to apply after text filtering.

## Detail Contract

The detail endpoint returns:

```text
ag_operational_event_detail_projection.v1
```

The projection includes the redacted `operational_event.v1` object and a small
summary with event id, service id, event type, severity, trace id, subject ref,
and created timestamp. Missing event ids return `ag.operational_event_not_found`.

## Safety

AG still relies on the shared operational event redaction path. Sensitive detail
keys such as authorization, token, password, secret, raw prompt, and source text
are not exposed by list or detail projections.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py tests/test_nex_runtime_app.py
```

Observed result:

```text
81 passed
```
