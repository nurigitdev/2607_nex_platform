# Slice 0049 AG Generation Recovery Audit Projection

Status: Implemented.

Backlog candidate: `S5-009` AG generation recovery audit projection.

Requirement coverage: `AG-FR-002`, `AG-FR-003`, `AG-FR-005`,
`AEAPI-FR-005`, `CX-FR-008`, `TRACE-GEN-001`, `PLAT-FR-007`.

## Scope

Slice 0049 extends the AG generation audit projection so operators can inspect
failure recovery intent:

- Existing endpoint
  `GET /admin/v1/generation-audit/generations/{cx_generation_id}` now accepts
  optional `recovery_request_id`.
- AG reads the AE recovery request through service-authenticated APIs.
- The projection includes `generation_summary.failure` and
  `recovery_request_summary`.
- The embedded `ag_generation_audit_event.v1` event records recovery request ID,
  requested action, and policy hash status in redacted details.
- Recovery audit examples reuse the existing AG audit event schema.

The slice remains read-only. AG does not approve, dispatch, mutate, or retry the
request.

## Files

- `services/nex-ag/nex_ag/generation_audit.py`
- `contracts/examples/generation/ag_generation_audit_event.recovery_retry.json`
- `contracts/tests/negative/generation/ag_generation_audit_event.recovery_raw_prompt_leak.json`
- `contracts/openapi/nex-ag.openapi.yaml`
- `tests/test_nex_ag_generation_audit.py`

## Evidence

Slice evidence should include:

```bash
./.venv/bin/pytest tests/test_nex_ag_generation_audit.py tests/test_contract_validation.py
scripts/quality/run_quality_gate.sh
```

Regression tests cover optional recovery request lookup, redacted failure
summary, recovery request summary, audit action mapping, route query handling,
HTTP AE recovery lookup, and raw prompt leakage rejection.
