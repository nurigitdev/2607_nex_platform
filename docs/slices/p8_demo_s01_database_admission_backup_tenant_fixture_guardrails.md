# P8-DEMO-S01: Database Admission, Backup, and Tenant Fixture Guardrails

## Scope

P8-DEMO-S01 closes the destructive-operation boundary that must precede any
Demo migration or fixture mutation. It admits the exact seven existing
development database and role identities, creates a complete pre-migration
logical backup set, and defines a fail-closed tenant-only seed/reset plan.

This Slice does not execute migrations, seed data, or reset data.

## Database Identity Admission

The admitted runtime variables and exact targets are:

| Service | Runtime variable | Database | Role |
| --- | --- | --- | --- |
| NeX-OA | `NEX_OA_DATABASE_URL` | `nex_oa_dev` | `nex_oa_user` |
| NeX-AG | `NEX_AG_DATABASE_URL` | `nex_ag_dev` | `nex_ag_user` |
| NeX-AE | `NEX_AE_DATABASE_URL` | `nex_ae_dev` | `nex_ae_user` |
| NeX-CX | `NEX_CX_DATABASE_URL` | `nex_cx_dev` | `nex_cx_user` |
| NeX-MO | `NEX_MO_DATABASE_URL` | `nex_mo_dev` | `nex_mo_user` |
| NeX-WC | `NEX_WC_DATABASE_URL` | `nex_wc_dev` | `nex_wc_user` |
| NeX-EOS | `NEX_EOS_DATABASE_URL` | `nex_eos_dev` | `nex_eos_user` |

The gate validates both URL metadata and live `current_database()` /
`current_user` results. It also rejects replicas and duplicate service-local
bindings. Its SQL is read-only: identity, recovery state, migration-table
existence, and applied migration versions only.

The actual check admitted all seven identities. Migration state remains:

```text
nex-oa      0 / 18  MIGRATION_REQUIRED
nex-ag      0 / 20  MIGRATION_REQUIRED
nex-ae-api  0 / 60  MIGRATION_REQUIRED
nex-cx      0 / 23  MIGRATION_REQUIRED
nex-mo      0 / 10  MIGRATION_REQUIRED
nex-wc      0 / 13  MIGRATION_REQUIRED
nex-eos     8 / 15  MIGRATION_REQUIRED
```

This is admission evidence, not permission to skip migration.

## Pre-Migration Backup

The existing S145 logical backup executor is reused through a policy-neutral,
service-scoped plan builder. The production S145 five-service policy and its
invariants are unchanged.

The Demo backup path requires:

- the complete ordered seven-database admitted set;
- exact confirmation `BACKUP_P8_DEMO_DEV_DATABASES`;
- an absolute, non-symlink backup root;
- ephemeral mode-`0600` libpq service/pass files;
- credentials excluded from command arguments, reports, and manifests;
- custom-format `pg_dump`, atomic archive publication, SHA-256, and mode-`0600`
  per-service manifests;
- one set manifest binding database/role identity, source inventory hash,
  applied/missing/extra migration inventory, and all seven archive hashes.

Actual pre-migration evidence:

```text
backup_root = /data/nex-platform/demo/postgres-backups
backup_id   = 20261025T094708Z-2181ccfc439cbe36
service_count = 7
set_hash = sha256:84ecde61de491258ca5358da3779f320efe29fa7ba5d077a041987a7a6e2d898
set_manifest_sha256 = 4e968bef482b2ab89536d2c20bc7425c3b1356aa50e138c0e910ffb5822e3205
pg_restore --list = 7 / 7 PASS
```

The source migration inventory was not applied before this backup.

## Demo Tenant Seed/Reset Boundary

The admitted tenant is exactly `p8-golden-a`. A fixture action is only a plan
until all of the following are true:

1. action is `SEED` or `RESET` and its exact action-specific confirmation is
   supplied;
2. the canonical fixture hash validates;
3. the plan references a valid complete seven-service pre-migration backup
   manifest;
4. all seven Demo databases are migration-current;
5. every mutation is explicitly tenant-predicated.

The current Golden A fixture owns seed records in OA and EOS. The lifecycle
scope nevertheless covers all seven services so later AE/WC/AG/CX/MO Demo
residue cannot be mistaken for a successful reset. Whole-database truncate,
drop, test reset helpers, wildcard tenant scope, and cross-tenant mutation are
not admitted.

Because the actual databases are not migration-current, seed/reset execution
remains closed after this Slice.

## Operator Command

With owner-scoped database URLs injected into the environment:

```bash
./.venv/bin/python scripts/deployment/run_p8_demo_database_guardrails.py \
  --check \
  --backup \
  --backup-confirmation BACKUP_P8_DEMO_DEV_DATABASES \
  --backup-root /data/nex-platform/demo/postgres-backups \
  --summary
```

The redacted local report is written to
`reports/deployment/p8-demo-database-guardrails.json` and is intentionally
ignored by Git.

## Verification

- focused guardrail and PostgreSQL backup regression: `44 passed`;
- new Demo guardrail coverage: statement `97.07%`, branch `95.92%`;
- existing PostgreSQL backup module coverage: statement/branch `100% / 100%`;
- Ruff and `git diff --check`: passed;
- actual PostgreSQL identity admission: `7/7` passed;
- actual custom-format backup creation: `7/7` passed;
- archive catalog readability with `pg_restore --list`: `7/7` passed;
- report credential/URL scan: no database URL or password present.

The `nex-runtime` Slice profile first ran `1,683 passed` and one protected
skip. Its historical whole-package scope reported `89.49%` statement and
`86.48%` branch because several shared modules are intentionally covered by
their owning service suites rather than the runtime-only selection. The
threshold was not reduced. Because this Slice changes shared runtime code, it
was escalated to the canonical Checkpoint Gate:

```text
16,844 passed
117 explicit protected skips
statement coverage 98.65%
branch coverage    97.13%
contracts          207 schemas / 271 positive / 231 negative / 9 OpenAPI
```

## Exit

P8-DEMO-S01 is complete when identity admission and the complete pre-migration
backup set pass. The next Slice may apply migrations only after rechecking this
evidence. Tenant seed/reset remains unavailable until migration-current state
and backup-manifest admission both pass.
