# MyBee Phase-1 S0-01: Frozen/HEAD/DB Source Baseline

## Scope

S0-01 records the implementation-entry source baseline without changing
runtime code, API behavior, database schema, or Frozen architecture.

## Artifacts

- `docs/mybee_phase1/baselines/source_manifest.json`
- `docs/mybee_phase1/baselines/repo_compatibility_owners.md`
- `domains/mybee/compatibility/platform.lock.json`
- `tests/test_mybee_d04d12_architecture_snapshot.py`

## Decisions

- `master@9fe6ddb151bd121c8fb66fbde62cc24cca29eddb` is the stable entry ancestor.
- Actual migration heads for all eight service databases are recorded.
- OA, AE, WC, EOS, WA ownership remains canonical and MyBee is an API consumer.
- NSL runtime remains the exact admitted v0.2.1 wheel lock.
- PDF reconciliation, PostgreSQL acceptance, public E2E, and finance sign-off
  remain open gates.

## Verification

```text
focused pytest
  tests/test_mybee_d04d12_architecture_snapshot.py
  4 passed

contract validation
  schemas=233
  examples=292
  negative_examples=245
  openapi=10
  result=PASS

migration source dry-run
  services=8
  source heads match source_manifest.json
  database mutation=NO

product Python changed=NO
statement/branch coverage impact=N/A
```

The generic `platform` Slice Gate coverage scope is intentionally not used as
coverage evidence for this document/manifest-only Slice; its service profile
has no MyBee product source target. Product coverage thresholds remain
unchanged and become applicable when `MB0-01` introduces the domain package.
