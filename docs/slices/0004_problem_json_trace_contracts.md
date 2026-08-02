# Slice 0004 Problem JSON And Trace Contracts

Status: Implemented.

Backlog candidate: `S1-004` Common problem+json and trace contract fixtures.

Requirement coverage: `PLAT-FR-003`, `PLAT-FR-004`.

## Scope

Slice 0004 adds common contract fixtures for request correlation and API error
responses:

- `contracts/schemas/common/problem_json.v1.schema.json`.
- `contracts/schemas/common/trace_refs.v1.schema.json`.
- Positive examples for `problem+json` and trace refs.
- Negative fixtures for missing trace ID, forbidden secret-like detail keys,
  and malformed `traceparent`.
- Negative fixture validation in `scripts/quality/validate_contracts.py`.
- Shared OpenAPI component entries for `ProblemJson` and `TraceRefs`.

## Contract Decisions

`trace_id` uses the W3C 32-character lowercase hex trace ID shape. `request_id`
uses a canonical lowercase UUID shape for operator support and log correlation.

`problem_json.v1` requires `type`, `title`, `status`, `detail`, `instance`,
`error_code`, `retryable`, `request_id`, `trace_id`, and `details`.

`details` must not expose common secret-like keys such as `password`,
`authorization`, `access_token`, `refresh_token`, `service_secret`,
`reset_token`, `activation_token`, or `cookie`.

## Evidence

Quality gate target:

```text
pytest with statement coverage and branch coverage
coverage threshold check
contract validation with positive and negative examples
```

## Follow-Up

Slice 0005 should use the common trace and error contract shape while adding
the OA service token mock and claim validation baseline.
