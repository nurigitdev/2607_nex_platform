# Slice 1040: AE-to-CX Asynchronous Generation PostgreSQL Smoke

## Goal

Prove the implemented AE-to-CX asynchronous generation lifecycle against the
actual AE and CX test PostgreSQL databases without relying on a remote model
provider.

## Implementation

- Added an opt-in smoke runner restricted to `nex_ae_user@nex_ae_test` and
  `nex_cx_user@nex_cx_test`.
- Runs both service migration plans before the write probe.
- Drives AE asynchronous chat admission through the real CX owner-scoped API,
  durable CX job/request persistence, bounded worker execution, generation
  handoff, and AE explicit refresh.
- Uses a deterministic mock generation provider; remote provider availability
  is outside this persistence/integration boundary.
- Verifies both database identities and roles, durable rows, transient content
  delivery, AE non-persistence of generated content, restart reads in both
  services, and cross-owner `404` isolation.
- Deletes AE chat/render-event/operational-event rows and CX
  job/admission/execution/event rows, then verifies zero probe residue.

## Protected Execution

```bash
NEX_AE_CX_ASYNC_POSTGRES_SMOKE=1 \
NEX_AE_TEST_DATABASE_URL='postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test' \
NEX_CX_TEST_DATABASE_URL='postgresql+psycopg://nex_cx_user:***@127.0.0.1:5432/nex_cx_test' \
./.venv/bin/python scripts/smoke/run_ae_cx_async_generation_postgres_smoke.py
```

The test wrapper uses the same variables. Without the explicit smoke flag, the
actual database test is skipped safely.

## Observed PostgreSQL Evidence

- Protected runner: `PASS`, 17/17 checks, no failed checks.
- Protected pytest: `6 passed`, no skipped test.
- AE identity: `nex_ae_user@nex_ae_test`.
- CX identity: `nex_cx_user@nex_cx_test`.
- AE migrations: 23 planned, 23 current, latest
  `1014_ae_workspace_activity_persistence`.
- CX migrations: 21 planned, 21 current, latest
  `0966_cx_generation_admissions`.
- Probe rows observed: one AE chat, three AE events, one CX job, and one CX
  generation execution.
- Restart reads returned AE `COMPLETED` and CX `SUCCEEDED` state.
- Generated content was returned transiently and was absent from the persisted
  AE generation summary.
- Cleanup residue: AE `0`, CX `0`.
- Slice Gate: `2219 passed`, one intentionally protected skip, and one known
  warning.
- Repository statement coverage: `97.91%`.
- Repository branch coverage: `95.71%`.
- Runner statement/branch coverage after focused redaction-boundary hardening:
  `100%`/`100%`.
- Contract validation: 98 schemas, 153 positive examples, 116 negative
  examples, and 7 OpenAPI documents.
