# Slice 0109: AG Operations Issue Candidate Projection

## Scope

Slice 0109 adds a read-only issue candidate endpoint:

```text
GET /admin/v1/operations/issue-candidates
```

This is the foundation for future alerting. It does not send notifications,
create acknowledgements, or mutate incident state.

## Response Shape

The projection schema version is:

```text
ag_operations_issue_candidate_projection.v1
```

The projection includes:

- rule definitions used for candidate detection
- issue candidates with stable candidate ids
- severity, service, and rule summaries
- job and event source statuses used to ground the candidates

## Rule Foundation

Initial rules are intentionally simple and deterministic:

- operations source unavailable
- operations source not configured
- failed jobs present
- `ERROR` events present
- `CRITICAL` events present
- active jobs present for operator review

Stuck-job duration rules, acknowledgements, escalation routing, and outbound
notification channels are deferred until the job worker heartbeat/runtime
contract is ready.

## Query Contract

The route supports:

- `service_id`
- `since`
- `until`
- `recent_limit`

The route reuses the dashboard snapshot signal set from Slice 0108 and keeps
`recent_limit` clamped to `1..20`.

## Contract Artifacts

Positive example:

```text
contracts/examples/operations/ag_operations_issue_candidates.mock_success.json
```

Negative example:

```text
contracts/tests/negative/operations/ag_operations_issue_candidates.missing_issue_candidates.json
```

The operations family schema now includes
`ag_operations_issue_candidate_projection.v1`.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_contract_validation.py tests/test_nex_ag_operations.py
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```
