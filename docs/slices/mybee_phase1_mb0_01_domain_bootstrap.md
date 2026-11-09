# MyBee Phase-1 MB0-01: Monorepo Domain Bootstrap

## Scope

MB0-01 introduces the installable `nex-mybee-ax` domain package without
creating a second repository, service runtime, database, or CI authority.

## Structure

```text
domains/mybee/
  pyproject.toml
  README.md
  compatibility/platform.lock.json
  mybee_ax/__init__.py
  mybee_ax/metadata.py

tests/mybee_phase1/
  test_bootstrap.py
  test_boundary_imports.py
```

The root pytest and coverage configuration now admits `domains/mybee`.
Because the repository has no existing `.github/workflows/ci.yml`, this Slice
does not invent a new workflow. Existing repository quality scripts remain the
single gate implementation.

## Boundary

- MyBee owns domain policy and canonical API consumers only.
- Service-private imports and direct PostgreSQL/ORM access are rejected.
- Runtime, service, database, and migration subtrees are rejected.

## Verification

```text
package wheel build
  nex_mybee_ax-0.1.0-py3-none-any.whl
  result=PASS
  build artifacts retained in repository=NO

focused package/boundary pytest
  6 passed

MyBee package coverage
  statement=100%
  branch=100% (no branches introduced)

Group 1 cumulative regression through MB0-01
  67 passed
  2 protected skips
  failures=0
```

The protected skips are the existing Golden A PostgreSQL/provider cases. They
remain admission-guarded and are not represented as live PASS evidence.
