# Slice 0133: Replay OpenAPI and Smoke Evidence

## Scope

Slice 0133 freezes the dead-letter replay surfaces introduced in Slices 0131 and
0132 as OpenAPI contract entries and extends the AG job-control smoke evidence
pack.

Implemented:

- AG OpenAPI path for operator-facing dead-letter replay dispatch
- AG `AgJobReplayRequest` schema with required replay metadata
- CX OpenAPI path for service-local internal dead-letter replay
- `replay` action support in AG dispatch and service-local response schemas
- `controls.can_replay` and `allowed_actions=replay` contract vocabulary
- AG job-control smoke coverage for cancel, retry, and replay

## Contract Boundary

AG owns the operator-facing replay dispatch surface:

```text
POST /admin/v1/operations/jobs/{service_id}/{job_id}/replay
```

CX documents the service-local replay target:

```text
POST /internal/v1/jobs/{job_id}/replay
```

Replay requires explicit operator metadata:

```text
replay_job_id
idempotency_key
requested_by
reason
observed_at=<optional>
```

The replay response exposes safe lineage and source-job summary fields only.
Source payloads and private error detail remain service-local.

## Smoke Evidence

The mock-first smoke now creates a failed dead-letter CX source job, dispatches
AG replay, and validates that:

- the source job remains `FAILED`
- the replay job is created as `QUEUED`
- replay lineage points back to the source job
- AG records cancel, retry, and replay audit events
- operator-facing smoke evidence stays payload-redacted

Expected summary:

```text
ag_job_control_smoke=pass actions=3 audit_events=3 cancel_status=CANCELLED retry_status=QUEUED replay_status=QUEUED
```

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_smoke_helpers.py tests/test_contract_validation.py
./.venv/bin/python scripts/smoke/run_ag_job_control_smoke.py --summary
./.venv/bin/python scripts/quality/validate_contracts.py
```
