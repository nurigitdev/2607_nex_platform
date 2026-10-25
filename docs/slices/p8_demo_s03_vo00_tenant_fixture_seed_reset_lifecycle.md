# P8-DEMO-S03: VO00 Tenant Fixture Seed / Reset Lifecycle

## Scope

P8-DEMO-S03 establishes the deterministic Demo tenant lifecycle after all
seven development databases became migration current. The exact tenant is
`VO00`. Seed and reset are bound to the P8-DEMO-S01 backup set and never use a
whole-database reset or a `*_test` helper.

## Canonical Fixture

The tracked fixture document is
`scripts/deployment/data/p8_demo_vo00_fixture.v1.json`. It binds:

- the immutable Golden A business fixture hash;
- tenant `VO00` and its display name;
- employee login identifiers `1001` and `2001` without passwords;
- deterministic Project memberships for the requester and approver;
- a semantic fixture hash covering all of the above.

The business fixture is derived without modifying the historical Golden A
document. Login passwords are supplied only through
`NEX_DEMO_CHAIRMAN_PASSWORD` and `NEX_DEMO_APPROVER_PASSWORD`; neither value is
written to the fixture, report, process arguments, or committed evidence.

## Tenant-Scoped Reset

The reset executor inspects each admitted database for `tenant_id` and
`tenant_ref_id` columns, derives a child-first order from live PostgreSQL
foreign keys, and executes only predicates for `VO00`. Tables that have no
tenant-scoped columns, such as the current MO provider catalog, are admitted
as zero-residue owners. An identity mismatch, FK cycle, unexpected tenant,
failed delete, or remaining row aborts the transaction.

## Deterministic Seed

The seed creates or verifies:

```text
OA
  tenant                         1
  subjects                       2
  tenant memberships             2
  local employee credentials     2

EOS
  NVTProject                     1
  Project                        2
  Project membership             2
  account                        2
  organization unit              4
  position                       1
  position assignment            1
```

The first seed requires a zero-residue tenant. A repeated seed performs no
mutation and succeeds only when the complete row-count and stable identity
set matches the fixture. Partial or additional state fails with
`demo_fixture_existing_state_conflict`.

## Actual PostgreSQL Evidence

```text
tenant_id = VO00
databases = 7 admitted *_dev databases

RESET replay:
  status = PASS
  services = 7
  rows_after = 0

SEED first run:
  status = PASS
  execution_state = SEEDED
  total_rows = 20

SEED exact replay:
  status = PASS
  execution_state = ALREADY_PRESENT
  total_rows = 20
  evidence_hash = sha256:bf6a02d9b7a2c0cbf116880d980babafd0db92b90cbabd7c72c12bf3a6e3cf25
```

Final distribution:

```text
nex-oa      tenant tables=13  VO00 rows=7
nex-ag      tenant tables=8   VO00 rows=0
nex-ae-api  tenant tables=46  VO00 rows=0
nex-cx      tenant tables=11  VO00 rows=0
nex-mo      tenant tables=0   VO00 rows=0
nex-wc      tenant tables=10  VO00 rows=0
nex-eos     tenant tables=19  VO00 rows=13
```

## Verification

- focused S01/S03 and Golden A regression: `93 passed`;
- `nex_runtime.demo_tenant`: statement `100%`, branch `99%`;
- actual PostgreSQL tenant reset: `7/7 PASS`, zero residue;
- actual PostgreSQL seed and exact replay: `SEEDED`, then `ALREADY_PRESENT`;
- credential and password inclusion flags: false;
- Ruff and `git diff --check`: passed.

## Exit

P8-DEMO-S03 is complete with the VO00 fixture intentionally preserved for
the installed Demo topology. P8-DEMO-S04 may now freeze and package the exact
runtime process inventory that consumes this durable state.
