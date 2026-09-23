# Slice 0969: CX Grounded Generation Live PostgreSQL and DGX Smoke

## Goal

Prove the S97 owner-private grounded-generation runtime against the actual CX
test database and the protected DGX OpenAI-compatible generation provider,
without writing prompts, retrieval evidence, generated content, credentials,
provider endpoints, or private storage locations into evidence.

## Implementation

- Added an explicit opt-in, test-profile-only protected smoke runner.
- Applied all current `nex-cx` migrations before execution and required the
  `nex_cx_test` database plus `nex_cx_user` role.
- Wired the SQL generation execution repository, SQL admission repository,
  owner-private filesystem output store, restart-safe read model, and SQL
  operational event store into the real CX generation route.
- Executed one grounded request through the DGX generation provider using the
  frozen `Qwen3.5-4B` model.
- Propagated the existing MO `reasoning_mode` control through the CX generation
  payload and included it in both request and idempotency semantic hashes. The
  bounded smoke selects `disabled`, matching the deterministic S96 summary
  lane and ensuring the provider returns final answer content rather than
  consuming the bounded output budget on reasoning tokens.
- Rebuilt the CX application to simulate a restart, replayed the same
  idempotency key, verified that no second provider call occurred, and reloaded
  both metadata and integrity-checked private content.
- Verified cross-owner metadata and content reads return `404`.
- Observed one durable execution, one terminal admission, and metadata-only
  completed/replayed operational events before deleting smoke rows and the
  temporary private output.
- Added deterministic regression coverage for activation, profile/model
  guards, configuration validation, bounded failures, safe projections,
  checks, redaction, and CLI behavior.

## Protected Execution

The live lane is disabled by default. It requires:

```bash
NEX_CX_GROUNDED_GENERATION_LIVE_POSTGRES_SMOKE=1 \
./.venv/bin/python \
  scripts/smoke/run_cx_grounded_generation_live_postgres_smoke.py --summary
```

The database URL, DGX base or chat-completions URL, and API key must be
provided through their existing protected environment variables. No secret is
accepted as a command-line argument or included in output evidence.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_cx_grounded_generation_live_postgres_smoke.py \
  tests/test_cx_grounded_generation_runtime_boundary_audit.py \
  --cov=run_cx_grounded_generation_live_postgres_smoke \
  --cov=run_cx_grounded_generation_runtime_boundary_audit \
  --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```

- Focused generation/runtime/live-smoke regression: `81 passed`.
- New protected smoke and boundary audit modules: `100%` statement and branch
  coverage in their focused suite.
- Protected live smoke checks: `12/12` passed.
- Full regression suite: `7487 passed`; statement coverage `98.89%`, branch
  coverage `96.62%`.
- Contract validation: `89` schemas, `140` examples, `105` negative examples,
  and `7` OpenAPI documents.
- Actual database identity: `nex_cx_test` owned session role `nex_cx_user`.
- Actual provider result: `COMPLETED` with `Qwen3.5-4B`; provider success count
  remained `1` after restart replay.
- Current migrations `0965_cx_grounded_generation_runtime` and
  `0966_cx_generation_admissions` were present in the actual test database.
- Post-smoke SQL verification found zero remaining execution, admission,
  retrieval-package, and operational-event rows for the smoke trace.

With this runner present, all eight S97 runtime gaps are resolved and the
boundary audit selects Slice 0970.
