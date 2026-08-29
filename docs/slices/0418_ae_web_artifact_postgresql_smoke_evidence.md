# Slice 0418: AE Web Artifact PostgreSQL Smoke Evidence

Status: Implemented.

Add a protected AE Web artifact PostgreSQL smoke runner that verifies the web
artifact surface is wired to the persisted AE artifact API and delegates the
actual write/readback flow to the existing `nex_ae_test` artifact smoke.

## Scope

Slice 0418 adds:

- `scripts/smoke/run_ae_web_artifact_postgres_smoke.py` as an optional
  test-profile-only smoke wrapper.
- Web boundary checks for artifact client, preview/download panel,
  versions/files panel, DOM slots, fake-fetch smoke, and quality-gate wiring.
- Delegated execution of `run_ae_artifact_postgres_smoke.py` with
  `NEX_AE_ARTIFACT_POSTGRES_SMOKE=1` and test profile when the wrapper is
  explicitly enabled.
- Redacted evidence summarizing migration status, persisted row counts,
  preview/download readback checks, local artifact file count, and cleanup.
- Regression tests for skip/guard/failure/pass evidence branches.

## Live Smoke

The smoke is skipped by default. To execute against the local AE test database:

```bash
NEX_AE_WEB_ARTIFACT_POSTGRES_SMOKE=1 \
NEX_AE_WEB_ARTIFACT_POSTGRES_SMOKE_PROFILE=test \
NEX_AE_TEST_DATABASE_URL='postgresql+psycopg://nex_ae_user:<password>@127.0.0.1:5432/nex_ae_test' \
./.venv/bin/python scripts/smoke/run_ae_web_artifact_postgres_smoke.py --summary
```

The runner must target a test database and must not print raw DB URLs,
passwords, provider API keys, `/data/nex-platform` paths, or physical storage
locations.

## Evidence

```bash
./.venv/bin/pytest tests/test_ae_web_artifact_postgres_smoke.py tests/test_ae_artifact_postgres_smoke.py -q
```

```bash
./.venv/bin/python scripts/smoke/run_ae_web_artifact_postgres_smoke.py --summary
```

```bash
NEX_AE_WEB_ARTIFACT_POSTGRES_SMOKE=1 \
NEX_AE_WEB_ARTIFACT_POSTGRES_SMOKE_PROFILE=test \
NEX_AE_TEST_DATABASE_URL='postgresql+psycopg://nex_ae_user:<password>@127.0.0.1:5432/nex_ae_test' \
./.venv/bin/python scripts/smoke/run_ae_web_artifact_postgres_smoke.py --summary
```
