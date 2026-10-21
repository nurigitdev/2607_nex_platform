# P8-S22 EOS Foundation Protected PostgreSQL Gate

## Scope

P8.2 closes with one protected acceptance journey against the actual
`nex_eos_test` PostgreSQL database. The gate fails closed unless the connection
target is exactly `nex_eos_user@nex_eos_test`.

The journey covers the S07-S21 vertical foundation:

- current migration head and actual database identity
- validated NeX-EOS version/build identity and readiness
- NVT Project, Project, and effective Account seed data
- fresh finance authorization through the P8-S17 authorization client
- protected Voucher command, attachment reference, and idempotent replay
- committed BusinessOperation reconciliation query
- side-effect-free Voucher verification with SELECT-only SQL observation
- exact business transaction, outbox, Voucher, line, and attachment counts
- cleanup in foreign-key order and zero tenant residue

The first live command exposed a real migration/runtime drift: the S19
canonical operation `FINANCE.CREATE_VOUCHER_DRAFT` was accepted by the Python
runtime while the original PostgreSQL constraints allowed underscore-only
operation names. Forward migration `2508_eos_operation_name_compatibility`
aligns both BusinessOperation and idempotency constraints without rewriting
the historical `2501` migration.

The authorization source and attachment resolver are deterministic protected
test doubles. PostgreSQL and the NeX-EOS persistence/API paths are live. OA,
RustFS, and remote model providers are not required by this P8.2 database gate.

## Verification

### Protected PostgreSQL smoke

- target: `nex_eos_user@127.0.0.1:5432/nex_eos_test`
- migration head: `2508_eos_operation_name_compatibility`
- result: `2 passed in 0.78s`
- verified mutations: one Voucher, two Voucher lines, one attachment reference,
  one BusinessOperation, one idempotency record, and one outbox event
- verified reference data: one NVT Project, one Project, and two Accounts
- verification read path: SELECT-only SQL observation with no mutation
- cleanup: all journey-owned rows removed; exact tenant residue count was zero

Command:

```bash
NEX_EOS_TEST_DATABASE_URL='postgresql+psycopg://nex_eos_user:<redacted>@127.0.0.1:5432/nex_eos_test' \
NEX_EOS_P8_S22_POSTGRES_SMOKE=1 \
NEX_EOS_P8_S22_BUILD_SHA=81ce8fb7 \
./.venv/bin/pytest -q tests/test_nex_eos_p8_s22_postgres.py -vv
```

### EOS Slice Gate

- pytest: `299 passed, 10 protected skips`
- statement coverage: `99.79%`
- branch coverage: `100.00%`
- contract validation: `176` schemas, `238` examples, `207` negative
  examples, and `9` OpenAPI documents

### P8.2 Full Gate

- pytest: `15,860 passed, 58 protected skips, 1,131 warnings`
- duration: `1,842.65s` (`00:30:42`) for the pytest/coverage phase
- statement coverage: `96.87%` (threshold `95.00%`)
- branch coverage: `96.27%` (threshold `85.00%`)
- contract validation: `176` schemas, `238` examples, `207` negative
  examples, and `9` OpenAPI documents
- complete gate command, including the subsequent compatibility and operations
  smoke chain: exit code `0`

The first Full Gate attempt correctly detected that the S129 closure test still
expected a fixed schema count of `174`. The test now derives its expected value
from the canonical contract inventory, and the complete Full Gate was rerun
from the beginning and passed. This preserves drift detection while avoiding a
new fixed-count failure whenever an admitted contract is added.
