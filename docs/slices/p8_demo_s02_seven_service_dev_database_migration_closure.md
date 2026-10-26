# P8-DEMO-S02: Seven-Service Dev Database Migration Closure

## Scope

P8-DEMO-S02 makes the seven admitted Demo development databases migration
current before tenant fixtures or installed runtime processes may mutate them.
It is bound to the complete pre-migration backup created by P8-DEMO-S01 and
does not admit a database rename, test-database fallback, or unknown migration.

## Guarded Execution

The migration closure validates, in order:

1. the exact seven `*_dev` database and owner-role identities;
2. the S01 backup set manifest and its semantic hash;
3. database, role, and source migration inventory equality with that manifest;
4. absence of extra/unknown migration versions;
5. the explicit confirmation `MIGRATE_P8_DEMO_DEV_DATABASES`;
6. ordered service-local migration execution through the canonical runner;
7. a fresh PostgreSQL inspection proving every database is `CURRENT`.

An interrupted run may resume only when the backup-time applied versions are
an exact prefix of the current canonical applied versions. Removal, reorder,
inventory change, identity change, or unknown version remains fail-closed.

## Actual PostgreSQL Evidence

The first execution stopped safely at CX migration `0933` because pgvector was
not provisioned. The first three services had already advanced through their
canonical migrations. After a database administrator installed pgvector 0.8.4
in `nex_cx_dev`, the same backup-bound command resumed without rollback.

```text
backup_id = 20261025T094708Z-2181ccfc439cbe36
status = PASS
service_count = 7
migration_current_count = 7
resumed_service_count = 4
newly_applied_migration_count = 38
evidence_hash = sha256:1794534e57bc005c47a20ce10eadbdee77ae27de621b9fdbdd8e3c2d0ccf69b1

nex-oa      18 / 18 CURRENT  applied=0  skipped=18
nex-ag      20 / 20 CURRENT  applied=0  skipped=20
nex-ae-api  60 / 60 CURRENT  applied=0  skipped=60
nex-cx      23 / 23 CURRENT  applied=8  skipped=15
nex-mo      10 / 10 CURRENT  applied=10 skipped=0
nex-wc      13 / 13 CURRENT  applied=13 skipped=0
nex-eos     15 / 15 CURRENT  applied=7  skipped=8
```

The ignored redacted report is
`reports/deployment/p8-demo-migrations.json`. It contains no database URL or
credential.

## Verification

- focused migration and S01 guardrail regression: `39 passed`;
- `nex_runtime.demo_migrations`: statement/branch `100% / 100%`;
- Ruff: passed;
- actual PostgreSQL migration closure: `7/7 CURRENT`;
- pgvector extension: `vector 0.8.4` in `nex_cx_dev`;
- migration URL/credential exposure: false;
- canonical Checkpoint Gate: `16,852 passed`, `117` protected skips;
- repository coverage: statement `98.65%`, branch `97.13%`;
- contracts: `207` schemas, `271` positive examples, `231` negative
  examples, and `9` OpenAPI documents.

The owner-only `nex-runtime` Slice profile reports its historical package-wide
coverage (`89.53%` statement, `86.56%` branch), even though the new module is
fully covered. Its threshold was not reduced; the shared change was escalated
to and passed the canonical Checkpoint Gate.

## Exit

P8-DEMO-S02 is complete. P8-DEMO-S03 may execute the tenant-scoped Demo
fixture lifecycle, using `VO00` as its exact tenant identifier.
