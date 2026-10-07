# Slice 1444: S145 PostgreSQL Backup Policy

## Outcome

- Added a strict policy for all five service-owned database targets.
- Froze custom-format logical backup every six hours, 28 restore points and
  seven-day retention, 30-minute service RTO, base backup plus WAL PITR, and a
  60-minute cluster RTO.
- Required PostgreSQL 16 tool compatibility, pgcrypto/vector extension
  inventory, a separately mounted production target, atomic publication, and
  libpq service/passfile credential transport.
- Rejected HA, automatic failover, password-bearing arguments, shared data
  volumes, incomplete ownership, duplicate bindings, and weakened objectives.

## Verification

The deterministic audit exposes only counts and policy identifiers. No host,
database name, user, password, URL, backup path, or row content is projected.

## Handoff

Slice 1445 uses this policy to create credential-safe atomic logical archives
and manifests.

