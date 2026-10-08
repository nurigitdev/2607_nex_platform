# PostgreSQL Single-Host Disaster Recovery Runbook

## Purpose

This runbook reproduces the S145 repository audits, logical restore, whole-
cluster point-in-time recovery, protected acceptance, closure, and Full Gate.
A pass proves an operator-controlled cold-recovery path for the five service-
owned PostgreSQL databases. It does not provide HA, automatic failover,
zero-downtime cutover, production deployment approval, or production-sized
RPO/RTO evidence.

## Operating Boundary

The accepted topology is one Docker Compose application host and one
PostgreSQL 16 cluster. OA, AG, AE, CX, and MO keep separate databases and
roles. The operator image is an opt-in recovery tool, not a seventh
application release image. It receives no Docker socket, runs as a non-root
user, and accesses only separate backup and credential mounts.

Production backup storage must have failure characteristics independent from
the PostgreSQL data volume. Repository and `/tmp` locations are rehearsal-
only. Provide PostgreSQL credentials through the approved libpq service and
passfile mounts. Never put credentials, connection strings, private rows,
backup contents, or physical storage paths in source-controlled evidence.

## Recovery Objectives

| Control | Admission target |
| --- | --- |
| Logical backup interval | 6 hours |
| WAL archive exposure | at most 300 seconds on a low-write cluster |
| Service-local restore RTO | 30 minutes |
| Whole-cluster restore RTO | 60 minutes |
| Logical retention | 28 points and at least 7 days |
| Physical retention | 2 verified base-backup generations |

These targets are budgets. S145 proves mechanics on test-sized data; S149 must
measure the same controls with production-sized staging data.

## Repository Audits

Run from the repository root:

```bash
./.venv/bin/python scripts/smoke/run_s145_postgresql_resilience_boundary.py --summary
./.venv/bin/python scripts/smoke/run_s145_postgresql_backup_policy.py --summary
./.venv/bin/python scripts/smoke/run_s145_logical_backup_execution.py --summary
./.venv/bin/python scripts/smoke/run_s145_isolated_restore_guard.py --summary
./.venv/bin/python scripts/smoke/run_s145_backup_catalog_retention.py --summary
./.venv/bin/python scripts/smoke/run_s145_postgresql_pitr_plan.py --summary
./.venv/bin/python scripts/smoke/run_s145_postgresql_backup_worker.py --summary
./.venv/bin/python scripts/smoke/run_s145_postgresql_compose_rehearsal.py --summary
```

All eight commands must report `pass`. The deterministic layer verifies the
five-target policy, atomic custom archives, destructive-target guard,
catalog/retention behavior, PITR pause plan, restart-safe worker, and hardened
Compose operator profile.

## Normal Backup Operation

1. Confirm the backup and WAL mounts are separate from PostgreSQL data and
   have private ownership and sufficient free space.
2. Materialize the two libpq credential files outside the repository.
3. Start only the `postgres-operations` Compose profile and run the operator
   worker. A concurrent worker must fail lock acquisition rather than overlap.
4. Require one atomic custom archive and value-free manifest for each service.
5. Run archive checksum, `pg_restore --list`, and all four restore probes
   before changing a point from `CREATED` to `VERIFIED`.
6. Quarantine stale partials. Retention may remove only points outside the
   28-point/seven-day floor and may never remove the last verified point.
7. Alert if no verified logical point is newer than six hours, WAL archival
   exceeds 300 seconds, or either retained base generation loses required WAL.

## Service-Local Restore

1. Declare the incident, identify the affected service, stop its writes, and
   record the selected verified recovery point and expected recovery time.
2. Provision an allowlisted `isolated_recovery` database. Never address the
   active source database or reuse its libpq service name.
3. Verify manifest shape, archive size, SHA-256, symlink absence, and archive
   listing before executing a single-transaction `pg_restore`.
4. Validate database identity, current migration head, representative query,
   required extensions, owner scope, and application readiness.
5. If any probe fails, discard the isolated target and select an earlier
   verified point. Do not overwrite or mutate the active source.
6. After review, an operator may schedule an explicit application cutover.
   Keep the previous target intact until rollback expiry and record actual RPO
   and RTO. There is no automatic cutover.

## Whole-Cluster PITR

1. Declare a cluster incident, stop all five service write paths, and prevent
   the application stack from restarting against the damaged cluster.
2. Select a verified base generation and recovery timestamp whose WAL chain is
   complete. Copy them to a new PostgreSQL data location; never recover in
   place over the previous cluster.
3. Configure the atomic WAL restore command, latest timeline, target timestamp,
   and `recovery_target_action=pause`. Start the isolated PostgreSQL 16 target.
4. Require recovery to remain paused and `pg_is_in_recovery()` to stay true.
   Validate all five database identities, 95 migration records, required
   extensions, table fingerprints, target-time marker behavior, and service
   readiness.
5. If validation fails, stop the target, preserve incident evidence, and
   retry from a different base/target. Never promote a failed target.
6. Only the designated PostgreSQL operator may approve promotion and endpoint
   cutover after service owners sign off. Promotion is never performed by an
   application, worker, or this runbook's audit commands.
7. Retain the previous cluster for rollback until the incident owner closes
   the observation window. Record actual RPO, RTO, chosen timeline, and the
   metadata-only evidence digest.

## Protected Acceptance

Inject the five `NEX_*_TEST_DATABASE_URL` values without persisting them, then
run:

```bash
NEX_S145_POSTGRES_RECOVERY_ACCEPTANCE=1 \
./.venv/bin/python \
  scripts/smoke/run_s145_postgresql_recovery_acceptance.py \
  --execute --summary
```

The sources must be the five actual test databases and remain read-only. The
runner restores them into an ephemeral PostgreSQL 16 cluster, takes a physical
base backup, archives and replays WAL to a paused target, and compares all five
fingerprints. A skipped run is not protected evidence. After the run, verify
the S145 marker table is absent in every source and no temporary PostgreSQL
process remains.

## Closure and Full Gate

```bash
./.venv/bin/python \
  scripts/smoke/run_s145_postgresql_resilience_closure.py \
  --summary
scripts/quality/run_quality_gate.sh
```

Closure must report eight of eight repository audits, eight closed gaps, five
actual databases, six WAL segments, zero residue, and `next=S146`. Full Gate
leaves the protected runner opt-in disabled and validates its metadata-only
attestation through the closure runner.

## Failure, Cleanup, and Escalation

Stop if credentials appear in arguments or evidence, the restore target can
address an active source, checksums or WAL are incomplete, PostgreSQL major or
extension versions differ, recovery does not pause, source residue appears,
or the operator needs Docker socket or privileged-container access. Stop the
ephemeral cluster using fast mode and immediate mode only as a bounded cleanup
fallback, remove run-scoped files, and confirm zero process and source residue.

Escalate stale recovery points to the five database owners and platform
integration. Escalate RPO/RTO misses, capacity limits, failure injection, and
production-sized recovery results to S149. S148 consumes the redacted backup,
archive-lag, recovery, and alert signals. S145 does not contact production or
approve deployment.

## Handoff

S145 closes the single-host PostgreSQL recovery mechanics and metadata-only
evidence boundary. S146 is next for private object-storage migration. S148 may
consume the recovery telemetry contract, while S149 must rerun recovery with
production-sized staging data before S150 can consider a go-live decision.
