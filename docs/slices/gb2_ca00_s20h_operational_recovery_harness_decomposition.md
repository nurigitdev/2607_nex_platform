# GB2-CA00-S20H: Operational Recovery Harness Decomposition

## Scope

- Isolate RustFS object-version cleanup and residue decisions.
- Isolate PostgreSQL recovery target, backup catalog, fingerprint, WAL replay, and cutover decisions.
- Isolate OA-backed trust denial and protected CLI exit-code decisions.
- Preserve actual protected RustFS, PostgreSQL, and OA acceptance entrypoints.

## Changes

- Added `scripts/smoke/operational_recovery_harness.py` with deterministic helpers for:
  - version/delete-marker cleanup batch validation;
  - bounded object-storage cleanup evidence;
  - recovery target coverage and verified backup catalog admission;
  - logical restore/PITR fingerprint and paused-cutover acceptance;
  - signed-trust denial projection;
  - strict and fail-only exit-code mapping.
- Rebound the S146, S145, and platform OA-backed trust runners to these helpers.
- Added malformed object inventory, catalog issue/partial/state, fingerprint drift, missing WAL, unsafe cutover, cluster cleanup, revocation denial, and exit-code tests.
- No service API, persistence schema, migration, object key, trust token, or backup format changed.

## Focused Regression

- Result: `30 passed, 2 skipped`.
- Skips were the explicitly protected S145 and OA-backed trust tests in the ordinary focused run.
- Deterministic helper statement coverage: `100%`.
- Deterministic helper branch coverage: `100%`.

## Protected Evidence

The protected tests were then enabled explicitly and run against local infrastructure:

- OA-backed trust: PASS against the actual OA, AE, CX, MO, and AG test PostgreSQL databases and loopback HTTP services.
- PostgreSQL recovery: PASS against all five test databases, including logical backup/restore, verified catalogs, ephemeral-cluster PITR, WAL replay, fingerprint equality, paused cutover, and source read-only preservation.
- RustFS object storage: PASS using the local Docker Compose RustFS/OpenBao staging boundary, actual test-database migration/probe, restart readback, version cleanup, and zero-secret evidence.

These acceptance paths do not require generation, embedding, or reranking providers.

## Slice Gate

- Platform Slice Gate: `443 passed, 9 skipped`.
- Target statement coverage: `100%`.
- Target branch coverage: `100%`.
- Contract validation: PASS (`227` schemas, `291` examples, `245` negative examples, `10` OpenAPI documents).
- Golden-journey transition audit: PASS.
- Demo/product dependency audit: PASS.

The Slice Gate's protected skips are not counted as live evidence; the three applicable acceptances above were enabled and executed separately.

## Remote Provider Boundary

Remote generation, embedding, and reranking providers were unavailable and were not contacted. S20H has complete applicable local infrastructure evidence without them.

## Outcome

Operational recovery acceptance now has a small, fully covered fail-closed decision layer, while the real Docker, PostgreSQL, RustFS, OpenBao, and signed-trust entrypoints remain intact and have current protected evidence.
