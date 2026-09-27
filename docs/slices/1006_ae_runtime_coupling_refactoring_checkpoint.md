# Slice 1006: AE runtime coupling and refactoring checkpoint

## Goal

Measure the current AE runtime coupling and freeze an ordered refactoring plan
without destabilizing the proven API, persistence, and provider boundaries.

## Decision

- P0: replace the duplicated authorization path in workspace, chat, and
  artifact-file delivery with the shared claim-authoritative facade guard.
- P1: introduce app-factory-owned runtime dependencies, then split artifact API
  and Web application composition by capability.
- P2: separate retention policy and execution logic from daemon process control.
- P3: replace production global stores with persistent adapters while retaining
  deterministic memory adapters for regression tests.
- Keep the existing provider and rendered-storage Protocol boundaries.
- Use incremental contract-preserving refactors; a big-bang rewrite is excluded.
- Slice 1006 changes no runtime behavior and adds no table.

Measured modules are the artifact API runtime, retention scheduler, retention
daemon, and Web application composition. Authorization helper duplication is
also counted from source rather than copied into the report by hand.

## Verification

```bash
./.venv/bin/python scripts/smoke/run_ae_runtime_coupling_audit.py --summary
./.venv/bin/pytest -q tests/test_ae_runtime_coupling_audit.py \
  --cov=nex_ae_api.runtime_coupling_audit \
  --cov=run_ae_runtime_coupling_audit \
  --cov-branch --cov-report=term-missing
```

Observed verification:

- Measured lines: artifact API `12,474`, retention scheduler `8,751`,
  retention daemon `21,023`, and Web composition `3,220`.
- Audit: PASS with `4` oversized modules, `8` required refactors, `8`
  duplicated authorization helpers, `2` good boundaries, and `0` evidence
  issues.
- Focused tests: `6 passed`; the audit module and runner both reached `100%`
  statement and branch coverage.
- Checkpoint Gate: `7,481 passed`; statement coverage `98.65%`; branch
  coverage `96.53%`.
- Contract validation: `92` schemas, `145` examples, `109` negative examples,
  and `7` OpenAPI documents passed.
