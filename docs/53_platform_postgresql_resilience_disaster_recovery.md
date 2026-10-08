# PostgreSQL Production Resilience and Disaster Recovery

Status: S145 complete through Slice 1452. Production deployment remains
unapproved.

## Required Outcome

S145 turns the existing five service-owned PostgreSQL databases into a
recoverable single-host production topology. It proves migration and pool
readiness, credential-safe logical backup, isolated service-database restore,
cluster base backup and WAL recovery, retention, restart-safe operation, and
measured RPO/RTO evidence.

The accepted deployment model is one Docker Compose application host and one
PostgreSQL cluster reachable from that host. High availability is not part of
S145: there is no synchronous replica, automatic leader election, replica
promotion, or transparent connection failover. Recovery is an explicit,
operator-controlled cold-recovery procedure.

## Single-Host Decision

The single-host topology is sufficient when all of these boundaries hold:

- OA, AE, CX, MO, and AG continue to own separate databases and credentials;
- custom-format logical backups provide service-local recovery while a
  physical base backup plus WAL archive provides whole-cluster PITR;
- backup execution never exposes a password or database URL in process
  arguments, logs, manifests, or source-controlled evidence;
- restore targets only an allowlisted recovery database or isolated recovery
  cluster and never overwrites an active source database;
- production backup data is written to a separately mounted backup target,
  not the PostgreSQL data volume or an application image layer;
- every backup is checksummed, catalogued, retention-managed, and restore
  tested before it is admitted as a recovery point; and
- protected evidence uses the five real test databases as read-only sources
  and an isolated PostgreSQL 16 cluster as the restore target, then leaves
  zero database or process residue.

No Kubernetes control plane or HA manager is required. PostgreSQL 16 client
and server tools, Docker Engine, Docker Compose, the repository Python runtime,
and a separately mounted backup target are sufficient. Production must use an
off-data-volume target with independent failure characteristics; a repository
or `/tmp` path is rehearsal-only.

## Recovery Objectives

| Objective | Target | Interpretation |
| --- | --- | --- |
| Logical-backup interval | 6 hours | Maximum admitted service-local RPO is six hours. |
| WAL archive interval | continuous, bounded by `archive_timeout=300s` | Whole-cluster PITR limits low-write WAL exposure to five minutes. |
| Service-local restore RTO | 30 minutes | Restore one database and validate migration/data probes. |
| Whole-cluster recovery RTO | 60 minutes | Restore a base backup, replay WAL, validate five databases, and decide cutover. |
| Logical retention | 28 restore points and at least 7 days | New backups cannot evict the last verified point. |
| Base-backup retention | 2 verified generations | WAL needed by retained base backups remains protected. |

These are admission budgets, not performance claims. Slice 1451 records the
rehearsal values, and S149 must reassess them with production-sized data.

## Existing Foundation

- Five test databases are migrated and restart-tested by S133.
- Every service has workload-specific pool size, overflow, pre-ping, recycle,
  pool timeout, and statement timeout controls.
- S143 provides external secret materialization and a single-host Compose
  topology; S144 proves protected execution and zero-residue cleanup.
- PostgreSQL 16.9, `pg_dump`, `pg_restore`, `pg_basebackup`, `pg_ctl`, and the
  pgvector 0.8.4 extension are available on the protected host.

## Gap Register

| Gap ID | Owner | Target Slice | Required result |
| --- | --- | --- | --- |
| `single_host_dr_boundary` | Platform integration and five database owners | `1443` | Freeze the no-HA cold-recovery model, objectives, ownership, stop conditions, and evidence boundary. |
| `backup_policy_contract` | Platform integration and five database owners | `1444` | Validate five targets, schedules, retention, storage separation, compatibility, and RPO/RTO budgets. |
| `logical_backup_execution` | Each database owner | `1445` | Create atomic custom-format backups and metadata without credential or partial-output admission. |
| `isolated_restore_guard` | Each database owner and platform integration | `1446` | Restore only to explicit recovery targets with destructive-source guards and probes. |
| `catalog_integrity_retention` | Platform integration | `1447` | Verify checksums, catalog state, retention, orphan quarantine, and run Checkpoint Gate. |
| `cluster_pitr_recovery` | PostgreSQL operator and platform integration | `1448` | Plan base backup, WAL archive, recovery target, timeline, and explicit cutover/rollback. |
| `restart_safe_backup_worker` | Platform integration | `1449` | Add exclusive execution, durable state, stale-run recovery, bounded retries, and safe exit codes. |
| `compose_rehearsal_acceptance_closure` | Platform integration and five database owners | `1450`, `1451`, `1452` | Bind Compose operations, actual restore/PITR evidence, runbook, attestation, and Full Gate. |

All gaps began `OPEN`. Unit tests and command-plan inspection could not close
the protected restore and PITR acceptance gap. Slice 1452 closes all eight
gaps after the protected five-database restore/PITR evidence was accepted.

Slice 1444 closes `backup_policy_contract`. The machine-validated policy binds
all five owners to distinct libpq services, PostgreSQL 16-compatible tools,
the pgcrypto/vector extension inventory, six-hour logical backups, 28 restore
points, seven days of retention, two base generations, five-minute WAL archive
exposure, and 30/60-minute service/cluster RTO budgets. Production storage must
be a separate mount and backup subprocess arguments may not carry credentials.

Slice 1445 closes `logical_backup_execution`. The executor uses a libpq
service/passfile boundary, restricts inherited environment values, streams
`pg_dump` custom output into a mode-0600 partial, fsyncs and hashes it, then
atomically publishes an archive and value-free `CREATED` manifest. A failed,
empty, duplicate, symlinked, or partially published run is never admitted.

Slice 1446 closes `isolated_restore_guard`. Restore admission verifies the
exact manifest shape, archive size and SHA-256, symlink absence, and a
`pg_restore --list` probe. Only the policy-bound `-recovery` service and
`isolated_recovery` class are accepted. A single-transaction restore must then
pass identity, migration-head, query, and extension probes.

Slice 1447 closes `catalog_integrity_retention`. Only an archive with a bound
four-probe restore sidecar becomes `VERIFIED`. Catalog scanning reports
manifest/archive/verification drift and orphans, stale partials move to a
private quarantine, and retention preserves the newest 28 points, seven days,
and at least one verified recovery point before any deletion is planned.

Slice 1448 closes `cluster_pitr_recovery`. A dedicated non-secret libpq
service drives a plain `pg_basebackup` with streamed WAL and a SHA-256 backup
manifest. WAL archive/restore commands validate segment names, copy atomically,
deny conflicting content, and verify digest sidecars. Recovery follows the
latest timeline and pauses at the target; promotion and cutover remain an
explicit operator decision after all five databases and migration heads pass.

Slice 1449 closes `restart_safe_backup_worker`. One non-blocking file lock
admits a run ID, and an atomically replaced mode-0600 state document records
attempts and the five service outcomes. A fresh `RUNNING` state is not stolen;
after 30 minutes it may be recovered and old partials are quarantined. Only
source-unavailable and dump failures retry, with bounded exponential delays
and at most three attempts. Terminal run IDs are idempotent and never execute
again implicitly.

Slice 1450 binds that worker boundary to a single-host Compose operations
profile. A dedicated non-root PostgreSQL 16.9 recovery-tool image remains
outside the six-image application release set. It receives two explicit bind
mounts and two external credential files, has no Docker socket or elevated
privilege, and is opt-in only. Deterministic rehearsal produces one catalogued
logical archive for each of the five services, while an actual container check
proves all three PostgreSQL 16 client tools without contacting a database.

Slice 1451 closes the protected recovery acceptance gap. All five actual test
databases were fingerprinted and dumped read-only, restored into an ephemeral
PostgreSQL 16 cluster, verified as five catalogued recovery points, captured by
physical base backup, and replayed through six archived WAL segments. Recovery
paused before a post-target marker, all 95 migration records and 121 public
tables matched, and no promotion occurred. The run completed in 13.326 seconds;
the protected pytest reported 3 passed with no skip. All five source databases
remained marker-free and no temporary PostgreSQL process remained.

The protected run found and fixed two real compatibility defects that command
planning alone could not expose: PostgreSQL supplies `RECOVERYXLOG` or
`RECOVERYHISTORY` as the restore destination, and `recovery_target_time` needs
PostgreSQL timestamp syntax rather than RFC3339 `T...Z` syntax.

Slice 1452 closes S145. The metadata-only attestation binds the accepted
source revision, policy, hardened operator profile, recovery image definition,
predecessor evidence, 10 protected checks, five database fingerprints, six WAL
segments, measured duration, and zero residue without tracking credentials,
raw rows, backup content, or physical paths. The operator runbook separates
service-local logical restore from whole-cluster PITR and requires recovery to
pause until an explicit operator cutover decision. All eight deterministic
audits and 64 audit checks are aggregated by the closure runner.

## Slice Sequence

| Slice | Scope |
| --- | --- |
| `1443` | Current-state audit, no-HA single-host decision, ownership, gaps, and non-drift rules. |
| `1444` | Five-database backup target, RPO/RTO, retention, storage, and compatibility policy. |
| `1445` | Credential-safe atomic logical backup execution and metadata manifest. |
| `1446` | Archive validation, isolated restore, destructive-target denial, and recovery probes. |
| `1447` | Catalog, checksum integrity, retention, partial-run quarantine, and Checkpoint Gate. |
| `1448` | Base backup, WAL archive, PITR target, timeline, cutover, and rollback planning. |
| `1449` | Restart-safe worker, exclusive lock, durable state, retry, and stale-run recovery. |
| `1450` | Single-host Compose operator profile and deterministic recovery rehearsal. |
| `1451` | Protected five-test-database backup and isolated PostgreSQL restore/PITR acceptance. |
| `1452` | Metadata-only attestation, runbook, Full Gate, closure, and S148/S149 handoff. |

## Non-Drift Rules

- HA, streaming replication, automatic failover, and zero-downtime database
  cutover are explicitly outside S145.
- Cold recovery requires an operator decision; an application may never
  promote or replace a PostgreSQL cluster.
- Service ownership and the prohibition on cross-service database reads stay
  unchanged.
- Passwords, database URLs, raw rows, private payloads, backup keys, and
  physical paths never enter source-controlled evidence.
- A local backup on the PostgreSQL data volume is not DR evidence. Production
  requires a separately mounted target.
- Logical backup is not transactionally atomic across five databases. Each
  database has a recovery point within one measured recovery-set window.
- PITR restores the whole PostgreSQL cluster; service-local recovery uses a
  logical archive and a distinct recovery database.
- Test databases are read-only sources during acceptance; destructive work is
  confined to an isolated cluster.
- Production contact, implicit cutover, and production approval are forbidden.
- Slice Gate runs for every Slice, Checkpoint Gate at Slice 1447, and Full Gate
  at Slice 1452.

## Stop Conditions

Stop before protected acceptance if a database URL or password must appear in
an argument or evidence file, a restore can address the active source target,
the backup target shares the PostgreSQL data volume in production, the
PostgreSQL major version or required extensions cannot be restored, a partial
archive can be admitted, WAL retention cannot cover a retained base backup, or
the isolated cluster cannot be removed cleanly. Also stop on any requirement
for privileged application containers, Docker socket mounting, automatic
promotion, production contact, or silent SQLite/memory fallback.

## Closure Decision

S145 is complete for the accepted single-host Docker Compose cold-recovery
boundary. The actual protected run used all five PostgreSQL test databases as
read-only sources and an ephemeral PostgreSQL 16 target. Logical restore,
catalog verification, physical base backup, WAL replay, paused PITR, migration
and extension fidelity, source cleanup, and process cleanup all passed.

High availability, streaming replication, automatic leader election,
automatic promotion, zero-downtime cutover, production contact, and production
deployment approval remain outside this result. The 13.326-second test-sized
run is not a production-sized RTO claim. Slice 1452 Full Gate passed with
12,767 tests, 98.03% statement coverage, 96.96% branch coverage, and contract
validation at 166 schemas, 228 examples, 196 negative examples, and 7 OpenAPI
files.

Completion signal: Met.

## S146, S148, and S149 Handoff

S146 is the next implementation requirement and moves CX/AE private payloads
behind production object-storage ports. S148 may consume redacted backup age,
WAL archive lag, restore result, RPO/RTO, and incident signals only after S146
and S147 also close. S149 must rerun service restore and whole-cluster PITR
with production-sized staging data, failure injection, measured budgets, and
rollback before S150 can consider a go-live decision.
