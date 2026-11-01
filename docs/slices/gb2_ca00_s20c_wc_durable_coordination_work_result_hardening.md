# GB2-CA00-S20C WC Durable Coordination and Work-Result Hardening

## Status

```text
Slice                         = GB2-CA00-S20C
Status                        = CLOSED
Product code change           = NONE
Database migration            = NONE
Public API contract change    = NONE
Remote model provider         = NOT REQUIRED
Actual WC PostgreSQL smoke    = PASS
Slice Gate                    = PASS
```

## Purpose

S20C hardens the active WC coordination and WorkResult persistence boundaries.
The source audit found correct product behavior with under-tested SQL success,
replay, conflict, lease-recovery, mapping, and storage-failure branches. The
smallest safe change was therefore focused test coverage rather than product
refactoring.

## Source Audit

```text
services/nex-wc/nex_wc/coordination.py
services/nex-wc/nex_wc/work_results.py
```

No new repository abstraction, table, migration, or public contract was
needed. The existing in-memory repositories remain deterministic unit-test
adapters, while PostgreSQL remains authoritative for transaction, restart,
and zero-residue claims.

## Hardening Coverage

`tests/test_gb2_ca00_s20c_wc_durable_boundaries.py` adds coverage for:

- routing success, missing WorkItem, stale route, and stale claim versions;
- atomic claim creation, expired-lease recovery, active-lease denial, and
  assignment recovery conflict;
- handoff outbox read, enqueue, delivery, execution-lineage conflict, and
  timestamp conversion;
- tenant-scoped parent claim authority and missing assignment behavior;
- WorkResult source/read-model mapping and JSON payload conversion;
- outbox not-found, update conflict, enqueue, delivery, and retryable storage
  failure classification;
- first-read and post-lock idempotent replay, semantic conflict, SQL identity
  race, row-count version conflict, and successful atomic commit;
- in-memory revision replay and missing WorkItem denial.

The fake SQL session is limited to deterministic repository branching. It does
not replace the protected PostgreSQL acceptance below.

## Verification

Focused regression and coverage:

```text
focused S20C tests                         = 24 passed
focused WC regression                     = 147 passed / 2 protected skips
coordination.py focused statement/branch  = 98.41% / 94.07%
work_results.py focused statement/branch  = 99.74% / 100.00%
```

Actual PostgreSQL protected smoke:

```text
NEX_WC_TEST_DATABASE_URL=nex_wc_test
tests/test_nex_wc_p7_s3_postgres.py
  = 2 passed
  = route/claim atomicity, restart readback, conflicts, zero residue

NEX_AE_TEST_DATABASE_URL=nex_ae_test
NEX_WC_TEST_DATABASE_URL=nex_wc_test
tests/test_ae_wc_p7_s6_postgres_smoke.py
  = 4 passed
  = current migrations, WorkResult/resume persistence, cleanup evidence
```

Credentials are not recorded in evidence.

Final Slice Gate:

```text
pytest                                   = 586 passed / 21 protected skips
nex-wc package statement / branch        = 95.67% / 95.44%
coordination.py statement / branch       = 98.41% / 94.07%
work_results.py statement / branch       = 99.74% / 100.00%
contract validation                      = PASS (227 / 291 / 245 / 10)
Golden Journey transition audit          = PASS
Demo-to-Product dependency audit         = PASS
Slice Gate exit code                     = 0
```

The 21 Gate skips are separately protected PostgreSQL, provider, and
Playwright scenarios. The WC PostgreSQL claims required by S20C were executed
explicitly and passed before the Gate. No generation, embedding, or reranker
provider was used.

## Decision

GB2-CA00-S20C is closed. The next Slice is `GB2-CA00-S20D: AE Result Resume
and Publication Hardening`.
