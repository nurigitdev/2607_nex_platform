# Slice 0970: S97 CX Grounded Generation Runtime Closure

## Goal

Close S97 only when the owner-private grounded-generation runtime, actual
PostgreSQL evidence, and protected DGX evidence remain complete and
machine-checkable.

## Closure

S97 closes as `READY_FOR_S98` with:

- canonical CX prompt assembly over owner-admitted READY retrieval evidence;
- strict terminal provider-output and selected-evidence citation validation;
- durable owner-private generated output with metadata-only public lineage;
- owner-scoped SQL execution and idempotent admission persistence;
- restart-safe metadata and integrity-checked private-content reads;
- metadata-only completed, failed, replayed, and read-failure events; and
- actual `nex_cx_test` plus live DGX `Qwen3.5-4B` execution, restart replay,
  owner-isolation, and cleanup evidence.

The closure runner fails closed when a required module, migration, contract,
document, quality hook, boundary decision, or live-evidence token is missing.
It reruns the S97 boundary audit and requires all eight historical gaps to be
resolved with no open issue.

## Frozen Boundary

- Execution remains bounded synchronous, idempotent, and durable
  write-through for S97.
- CX owns grounded prompt assembly and treats retrieved content as untrusted
  context.
- PostgreSQL stores only metadata, hashes, lineage, citations, and validation
  outcomes. Full generated text remains in owner-scoped private storage.
- Cross-owner reads remain indistinguishable from missing data.
- The current generation target is `Qwen3.5-4B` on provider port `9111`.
- `reasoning_mode` is request-bound and included in idempotency semantics.
- Asynchronous workers, streaming transport, multi-attempt citation repair,
  and production provider SLO baselines remain deferred.
- S98 is the next requirement; its title and detailed Slice plan are not
  inferred by this closure.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_s97_cx_grounded_generation_runtime_closure.py \
  tests/test_cx_grounded_generation_runtime_boundary_audit.py \
  --cov=run_s97_cx_grounded_generation_runtime_closure \
  --cov=run_cx_grounded_generation_runtime_boundary_audit \
  --cov-branch --cov-report=term-missing
./.venv/bin/python \
  scripts/smoke/run_s97_cx_grounded_generation_runtime_closure.py \
  --summary
./scripts/quality/run_quality_gate.sh
```

Observed results:

- Focused closure and boundary regression: `11 passed`; both runner modules
  reached `100%` statement and branch coverage.
- S97 runtime integration regression: `150 passed`.
- Closure summary: `PASS`, components `8/8`, resolved gaps `8/8`, protected
  live checks `12`, next requirement `S98`.
- Full regression: `7,493 passed`.
- Full statement coverage: `98.89%`.
- Full branch coverage: `96.62%`.
- Contract validation: `89` schemas, `140` examples, `105` negative examples,
  and `7` OpenAPI documents.
- Full quality gate exit status: `0`.

The protected PostgreSQL/DGX lane was not repeated in this closure Slice. Its
actual execution, restart replay, owner-isolation, and cleanup evidence was
completed in Slice 0969 and is required by the closure runner.
