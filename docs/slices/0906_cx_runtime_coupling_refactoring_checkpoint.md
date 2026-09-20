# Slice 0906: CX runtime coupling and refactoring checkpoint

## Goal

Identify the smallest structural refactoring required before adding S92 CX
features, while preserving proven repository and provider boundaries.

## Findings

- Five couplings require refactoring: import-time singleton mutation, the broad
  `ContentIngestionStore`, concrete store dependencies in routes, duplicated
  service authorization helpers, and global generation execution state.
- Memory fallback remains useful for deterministic regression and is accepted
  for now.
- `CxContentRepository` and MO/extractor provider protocols are good boundaries
  and should be retained.
- Twelve CX modules currently duplicate `_authorize_cx_request`.

## Ordered Refactoring

1. Centralize `CxAccessContext` derivation and service authorization.
2. Introduce app-factory-owned `CxRuntimeDependencies` without import-time
   singleton mutation.
3. Extract private text and vector payload ports.
4. Narrow route dependencies to capability protocols.
5. Keep deterministic memory adapters for regression.

This is a targeted sequence, not a big-bang rewrite. Public routes and
contracts remain stable per Slice. No table, migration, or runtime behavior is
changed here.

## Verification

```bash
./.venv/bin/python scripts/smoke/run_cx_runtime_coupling_audit.py --summary
./.venv/bin/pytest -q tests/test_cx_runtime_coupling_audit.py \
  --cov=nex_cx.runtime_coupling_audit \
  --cov=run_cx_runtime_coupling_audit \
  --cov-branch --cov-report=term-missing
```

Observed verification:

```text
audit: PASS refactor_required=5 good_boundaries=2 auth_helpers=12
focused tests: 4 passed; target statement/branch coverage: 100%
aggregate regression: 6302 passed, 1 known warning
statement=75886/76767=98.85237146169578%
branch=17668/18318=96.45157768315319%
contract validation: 82 schemas, 133 examples, 97 negative examples, 7 OpenAPI
```
