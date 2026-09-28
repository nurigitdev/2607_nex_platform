# Slice 1070: AE Generated-Response PostgreSQL Smoke

## Goal

Prove the S107 durable generated-response flow against the actual AE and CX
test PostgreSQL databases and a private local-filesystem storage adapter.

## Protected Execution

```bash
NEX_AE_GENERATED_RESPONSE_POSTGRES_SMOKE=1 \
NEX_AE_TEST_DATABASE_URL=<redacted-nex_ae_test-url> \
NEX_CX_TEST_DATABASE_URL=<redacted-nex_cx_test-url> \
./.venv/bin/pytest -q tests/test_ae_generated_response_postgres_smoke.py
```

The runner accepts only `nex_ae_user@nex_ae_test` and
`nex_cx_user@nex_cx_test`. It applies both migration chains before the probe,
redacts database credentials, and uses a deterministic local generation client;
remote providers are not required for this persistence boundary.

## Evidence

- Protected test: `6 passed`; the actual smoke was executed, not skipped.
- Database identities: `nex_ae_user@nex_ae_test` and
  `nex_cx_user@nex_cx_test`.
- Migrations current: AE `23/23`, latest
  `1014_ae_workspace_activity_persistence`; CX `21/21`, latest
  `0966_cx_generation_admissions`.
- Probe rows observed: AE chat `1`, AE operational events `5`, CX job `1`, CX
  generation execution `1`.
- READY content was stored as one mode-`0600` private file; PostgreSQL retained
  only lineage metadata without raw content or an `ae://` storage ref.
- A new AE database engine and a new local storage adapter recovered the exact
  response after restart; cross-owner AE/CX reads returned not found.
- Cleanup evidence: AE remaining `0`, CX remaining `0`.
- Boundary progress: gaps `8`, open `0`, resolved `8`, next Slice `1071`.

## Slice Gate

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_generated_response_postgres_smoke.py \
  --test tests/test_ae_cx_async_generation_postgres_smoke.py \
  --test tests/test_nex_ae_generated_response_storage.py \
  --smoke scripts/smoke/run_ae_generated_response_lineage_boundary_audit.py
```

Slice Gate evidence: `2485 passed`, `4 skipped` protected PostgreSQL tests;
statement coverage `98.01%`, branch coverage `95.96%`; contracts `103/161/124/7`.
