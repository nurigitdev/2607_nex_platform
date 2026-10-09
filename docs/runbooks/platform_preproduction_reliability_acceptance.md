# Platform Pre-production Reliability Acceptance Runbook

This runbook closes S149 on the Single-host Docker Compose staging topology.
It never authorizes production deployment or distributed-failover claims.

## Admission

- Use the exact Slice 1490 release candidate and immutable six-image digest.
- Require passing Slice 1490, 1491, 1492, and 1493 metadata reports.
- Confirm all five test databases, Docker, RustFS prerequisites, DGX routes,
  and SSH runtime observation are available before protected execution.
- Keep credentials in the operator environment. Do not place them in commands,
  reports, logs, Markdown, or source control.

## Protected Execution

Run the protected stages in order with their documented environment bindings:

```bash
NEX_S149_SINGLE_HOST_LIVE_ACCEPTANCE=1 \
  ./.venv/bin/python scripts/smoke/run_s149_single_host_live_acceptance.py \
  --execute --summary

NEX_S149_RELEASE_BOUND_TARGET_WORKLOAD=1 \
  ./.venv/bin/python scripts/smoke/run_s149_release_bound_target_workload.py \
  --execute --summary

NEX_S149_UNDER_LOAD_ACCEPTANCE=1 \
  ./.venv/bin/python \
  scripts/smoke/run_s149_under_load_fault_security_rollback.py \
  --execute --summary

NEX_S149_EVIDENCE_ADMISSION=1 \
  ./.venv/bin/python scripts/smoke/run_s149_evidence_admission.py \
  --execute --summary
```

Generation health probes must report `reasoning_mode=disabled`. Never stop or
reconfigure DGX provider processes for S149 fault injection.

## Full Gate

Run the complete deterministic regression from a clean committed worktree:

```bash
./scripts/quality/run_quality_gate.sh
```

Then bind the fresh JUnit and coverage evidence to the admitted release:

```bash
NEX_S149_CLOSURE=1 \
  ./.venv/bin/python \
  scripts/smoke/run_s149_preproduction_acceptance_closure.py \
  --admission reports/deployment/s149-evidence-admission.json \
  --junit reports/coverage/junit.xml \
  --coverage reports/coverage/coverage.json \
  --output reports/deployment/s149-closure.json \
  --summary
```

Closure requires zero failed tests, statement coverage at least 95%, branch
coverage at least 94%, all S149 runners registered once, and ten closure checks.

## Failure Triage

1. Stop before push when any protected runner, exact operation count, digest,
   cleanup, Full Gate, or closure check fails.
2. Preserve only metadata-safe evidence. Use nested failure codes and local
   runtime logs for diagnosis; do not copy credentials or private payloads.
3. Separate environment availability, stale release identity, runtime defect,
   and acceptance-harness defect before changing code or rerunning a long load.
4. Re-run the smallest failed protected stage, then repeat every downstream
   report whose digest chain depends on it.

## Cleanup And Residue

- Require zero S149-owned PostgreSQL rows after every workload and fault run.
- Require RustFS bucket/version cleanup and removal of rehearsal volumes.
- Require provider rollout rehearsal residue to be zero.
- Confirm no staging Compose project remains and no provider process was
  mutated. Do not delete committed user data during cleanup.

## External Notification Waiver

External notification is `EXTERNAL_NOT_ACTIVATED`. A production GO requires a
time-bounded P1 waiver, named approver, expiry, and local compensating control.
S149 closure and S150 planning do not grant that waiver.

## Single-host Backlog

Keep these capabilities as `NOT_APPLICABLE_SINGLE_HOST`: multi-node service
failover, PostgreSQL automatic failover, object-store node loss, GPU
autoscaling/failover, and external dead-man monitoring. They require a future
distributed topology and cannot be represented as passing evidence here.

## S150 Handoff

A passing closure activates S150 with the production GO guard still enabled.
Carry forward the immutable release identity, five distributed backlog items,
external-notification waiver, local compensating control, and the rule that
`production_deployment_approved` remains false.
