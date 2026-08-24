# Slice 0327: AG Generation Quality Issue Detail API Wiring

## Scope

Expose the Slice 0326 generation quality issue detail/runbook projection through
the AG generation audit read API.

The endpoint remains read-only and source-backed. It assembles the normal
`ag_generation_audit_projection.v1` through the existing CX/AE audit source
client, then derives the redacted operator detail projection from that result.

## Implemented

- Added:
  - `GET /admin/v1/generation-audit/generations/{cx_generation_id}/quality-issue-detail`
- Reused the existing AG service-token authorization boundary.
- Reused existing query parameters:
  - `artifact_handoff_id`
  - `recovery_request_id`
- Reused existing source error mapping for `404` and `503`.
- Added regression coverage for:
  - unauthorized requests;
  - successful warning runbook projection;
  - source error mapping;
  - raw prompt redaction.
- Added the endpoint to `contracts/openapi/nex-ag.openapi.yaml`.

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_ag_generation_audit.py -q
21 passed, 1 warning
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2215 passed, 1 warning
statement_coverage=98.55%
branch_coverage=95.48%
contract_validation=pass schemas=51 examples=83 negative_examples=60 openapi=7
```
