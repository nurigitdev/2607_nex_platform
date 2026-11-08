# GB2-CA00-S20G: Canonical Journey Harness Decomposition

## Scope

- Decompose deterministic decisions used by the P8-S53 approval-resume, S135 authenticated-ingestion, and P8-S112 NVT membership acceptance runners.
- Preserve the existing protected PostgreSQL, remote-provider, and Playwright entrypoints.
- Exercise denial, malformed collaborator output, retry, cleanup, and process exit-code behavior without claiming unavailable remote-provider evidence.

## Changes

- Added `scripts/smoke/canonical_journey_harness.py` as the shared deterministic decision boundary for:
  - approval-resume scenario admission and lineage checks;
  - authenticated-ingestion cleanup and residue classification;
  - NVT membership backend/browser acceptance checks;
  - strict and fail-only CLI exit-code mapping.
- Rebound the three protected runners to the shared helper while retaining their I/O orchestration and public CLI behavior.
- Added DB-less tests for malformed scenario documents, failed commands, non-object JSON, ingestion retry and terminal failure, early worker exit, residue failure, protected-value redaction, and exit-code mapping.
- No service API, database schema, migration, provider route, or browser contract changed.

## Focused Regression

- Result: `30 passed, 1 skipped`.
- The skipped test is the explicitly protected P8-S53 PostgreSQL entrypoint; deterministic orchestration did not rely on it.
- Shared helper statement coverage: `100%`.
- Shared helper branch coverage: `100%`.

## Slice Gate

- Platform Slice Gate: `444 passed, 9 skipped`.
- Target statement coverage: `100%`.
- Target branch coverage: `100%`.
- Contract validation: PASS (`227` schemas, `291` examples, `245` negative examples, `10` OpenAPI documents).
- Golden-journey transition audit: PASS.
- Demo/product dependency audit: PASS.

Protected skips in the ordinary Slice Gate are not represented as live evidence.

## Actual PostgreSQL Evidence

P8-S53 remains intentionally pinned to the admitted NSL v0.2.0 release identity. The current `/home/tprover/2608_nsl` checkout is newer and correctly failed closed when combined with the v0.2.0 lock. The smoke was therefore rerun from a detached temporary checkout at the exact locked revision `c0a8d4e125ee129c4556d896356237bb3973582d` without modifying the current NSL working tree.

- AE database: `nex_ae_test` as `nex_ae_user`.
- WC database: `nex_wc_test` as `nex_wc_user`.
- Result: PASS, `10/10` checks.
- `actual_postgres=true`.
- `p8_4_closed=true`.
- EOS mutation count: `0`.

## Remote Provider Boundary

Generation, embedding, and reranking providers were unavailable in the current environment. They are not required for S20G deterministic harness decomposition or the exact-lock P8-S53 PostgreSQL evidence. P8-S112 live provider and Playwright acceptance was not rerun and no live-provider claim is made.

## Outcome

Canonical journey runners now share a small, fully covered deterministic decision layer while retaining their real protected integration entrypoints. Legacy release pins fail closed on source drift and remain reproducible from their admitted source revision.
