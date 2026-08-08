# Slice 0134: Dead-Letter Replay Issue Dashboard Surfacing

## Scope

Slice 0134 surfaces replayable dead-letter jobs in AG operations projections so
operators can discover replay candidates before calling the replay dispatch
endpoint.

Implemented:

- dashboard `replay_candidates` list for failed jobs with `error.dead_lettered=true`
- issue candidate rule `dead_letter_replay_available.v1`
- replay control hints with AG replay path and required payload fields
- AG operations contract schema updates for `replay_candidates`
- mock-first dashboard smoke evidence for replay candidate visibility

## Dashboard Signal

The dashboard keeps `recent_failures.jobs` as the general failed-job list. A
separate `replay_candidates` list includes only failed dead-letter jobs and
exposes safe operator hints:

```text
recommended_action=replay
allowed_actions=[read, replay]
control_path=/admin/v1/operations/jobs/{service_id}/{job_id}/replay
required_payload_fields=[replay_job_id, idempotency_key, requested_by, reason]
```

Job payloads are not copied into the replay candidate projection.

## Issue Candidate Rule

`dead_letter_replay_available.v1` is a `WARNING` rule. The general failed-job
condition remains `ERROR` through `failed_jobs_present.v1`; the replay rule is a
separate actionability signal.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py tests/test_smoke_helpers.py tests/test_contract_validation.py
./.venv/bin/python scripts/smoke/run_ag_operations_dashboard_smoke.py --summary
./.venv/bin/python scripts/quality/validate_contracts.py
```
