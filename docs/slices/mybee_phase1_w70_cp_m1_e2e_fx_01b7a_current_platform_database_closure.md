# CP-M1-E2E-FX-01B.7A: Current Platform Eight-Database Backup and Migration Admission Closure

## Purpose

The protected product closure found that canonical installed acceptance
requires OA, AG, AE, CX, MO, WC, EOS, and WA, while the inherited P8 Demo
backup and migration admission covered only seven databases. This Slice closes
that packaging and recovery gap before `CP-M1-E2E-FX-01B.7` resumes.

## Contract

- The current development release set is exactly eight databases.
- A backup manifest is valid only when all eight admitted database identities
  and their source migration inventories are present in canonical order.
- Backup and migration use distinct explicit confirmation values.
- A P8 Demo seven-database manifest cannot authorize current-platform
  migration.
- Migration rejects identity drift, extra migrations, changed source
  inventory, post-backup database changes, dry-run execution, and a non-current
  final state.
- Database URLs, passwords, and confirmation values are absent from reports.
- Historical P8 Demo seven-database backup and tenant-fixture contracts remain
  unchanged.

## Implementation

- Added a current-platform target set by extending the historical seven-core
  inventory with NeX-WA.
- Added current-platform admission, backup manifest, manifest validation, and
  migration execution schemas.
- Added `run_canonical_platform_database_guardrails.py` for read-only admission
  and optional all-eight logical backup.
- Promoted `run_canonical_platform_migrations.py` to require the all-eight
  manifest and current-platform confirmation.
- Preserved `run_p8_demo_migrations.py` as an explicit historical seven-core
  mode; it cannot silently select the current eight-database contract.
- Promoted installed acceptance to use the same eight-database source.

## Protected Execution

The protected sequence is:

1. inspect all eight live development databases;
2. create one logical backup set and immutable manifest;
3. apply admitted migrations in canonical service order;
4. reinspect all eight databases and require `CURRENT`;
5. retain redacted guardrail and migration evidence under `reports/deployment/`.

`CP-M1-E2E-FX-01B.7` may resume only after this sequence passes without
database drift or partial-release residue.

## Verification

- Focused guardrail, migration, installed-acceptance, and deployment-audit
  regression: `126 passed`.
- Pre-migration live admission: eight identities admitted, three databases
  current, five requiring migration, and no extra migration drift.
- Backup set: `20261118T082047Z-01b7a001`, eight private `0600` archives,
  schema `current_platform_pre_migration_backup_set.v1`, and set hash
  `sha256:fa5749ef04ac434b4d192c9c256b07811beae634bb6745bc26c6ad6f1acb8c12`.
- Actual migration: 47 migrations applied in total: OA 2, AE 3, WC 1,
  EOS 33, WA 8; AG, CX, and MO were already current. The redacted migration
  evidence hash is
  `sha256:acfcdc94065af83b00547a0e50a32a4a1d71374dcb836c3ed4d30df224e65c81`.
- Post-migration live admission: eight of eight databases `CURRENT` with no
  source or database drift.
- Exact migration replay against the same backup manifest: eight databases
  remained current and zero migrations were reapplied.
- Redaction audit: no database URL, password, backup confirmation, or migration
  confirmation was present in repository evidence.
- Owned guardrail coverage: statement `97.70%`, branch `96.72%`; database
  guardrail module `97.31%/95.92%` and migration module `100%/100%`.
- Contract validation, Golden Journey transition audit, and Demo product
  dependency audit: `PASS`.

The broad historical `nex-runtime` profile executed `2,120 passed, 1 skipped`,
but its repository-wide shared-module coverage remained at the pre-existing
non-admitted baseline of statement `86.97%`, branch `83.99%`. It includes
shared modules outside that profile's test ownership and is not used to claim
this Slice's coverage. The original Repository Full Gate remains assigned to
the resumed `.7` closure.

The protected backup archives remain outside the repository under
`/data/nex-platform/current/postgres-backups`. Repository evidence stores only
redacted identities, counts, and hashes.
