# Slice 1443: S145 PostgreSQL Resilience Boundary

## Outcome

- Re-audited the five service-owned databases, migration runner, pool controls,
  S133 restart evidence, and S143 single-host Compose dependency.
- Froze S145 as operator-controlled cold recovery. HA, streaming replicas,
  leader election, and automatic failover are not implemented or claimed.
- Split recovery into service-local logical archives and whole-cluster
  base-backup/WAL PITR.
- Set initial budgets of six-hour service RPO, five-minute WAL exposure,
  30-minute service restore RTO, and 60-minute cluster RTO.
- Registered eight gaps across ten Slices and fail-closed stop conditions.

## Feasibility

The single-host Compose topology is sufficient. Protected restore validation
uses an isolated PostgreSQL 16 cluster on the same host, so the five real test
databases remain read-only sources and need no `CREATEDB`, replication, or
superuser grant. Production still requires a separately mounted backup target;
a local path is rehearsal-only.

## Verification

- The boundary audit validates thirteen repository and policy checks.
- All eight gaps are assigned to Slices 1443 through 1452.
- The audit is registered exactly once in Full Gate.

## Handoff

Slice 1444 turns these decisions into a machine-validated backup policy. No
database table or application service contract changes are required here.

