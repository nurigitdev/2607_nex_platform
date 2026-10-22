# P8-S53: Approval Resume Protected PostgreSQL Gate

## Status

Completed on 2026-10-22.

## Scope

- Executed the admitted NSL v0.2 wheel in an isolated worker against the
  actual `nex_ae_test` and `nex_wc_test` PostgreSQL databases.
- Compiled and executed the canonical `LOCAL_SKILL` controlled-WRITE fixture
  through the read prefix and stopped at `WAITING_FOR_APPROVAL`.
- Published the protected AE ApprovalRequest and wait registration, resolved
  the WC approval decision, persisted immutable Platform ApprovalEvidence,
  accepted the typed approval event, and claimed the deterministic
  `RESUME_EXECUTION` RuntimeJob.
- Invoked the admitted public `ApprovalResumeCoordinator` with the exact
  P8-S51A `ResumeToken` contract.
- Covered approve, reject, expiry, and lineage-mismatch paths while stopping
  before every EOS mutation.

## Protected Evidence

The protected runner verified all 10 acceptance checks:

- the exact AE and WC test database roles and database names were used;
- all 57 AE and 13 WC migrations were already current;
- the admitted NSL release revision, source tree, wheel digest, and admission
  hash matched the lock;
- mismatched evidence was rejected before RuntimeJob creation;
- approve resumed with `VALID` / `APPROVED` and consumed the checkpoint;
- reject resumed with `VALID` / `REJECTED` without opening the write gate;
- expiry resumed with `EXPIRED` / `EXPIRED` without opening the write gate;
- each RuntimeJob reached `DONE` with exact execution, operation, wait,
  approval, and checkpoint lineage;
- all inserted AE and WC evidence was cleaned up;
- EOS mutation count remained zero.

The ignored local evidence report is
`reports/quality/p8-s53-approval-resume-postgres.json`. It contains no
passwords; database URLs are redacted.

## Compatibility Corrections

The actual PostgreSQL journey exposed a portable-type boundary that SQLite did
not reveal: `ae_wait_registration.wait_id` is UUID while
`ae_runtime_job.wait_id` is TEXT. The persisted join now compares an explicit
text cast of the UUID, preserving both existing schemas and avoiding a new
migration.

The Full Gate also exposed a stale duplicated S141 loopback baseline. The
S141 closure now consumes the canonical coupling audit constants instead of
repeating numeric values. This keeps production-readiness closure aligned when
the audited source inventory changes.

No production table, migration, or remote model-provider dependency was added
by P8-S53.

## Verification

- Focused S53 regression: `7 passed`, `1 protected skip`.
- Focused S141/coupling/S53 reconciliation: `16 passed`, `1 protected skip`.
- Actual PostgreSQL protected gate: `10/10` checks passed against
  `nex_ae_test` and `nex_wc_test`.
- AE Slice Gate: `4,801 passed`, `24 skipped`.
- AE Slice Gate coverage: statement `98.36%`, branch `96.27%`; changed resume
  module statement and branch coverage were both `100%`.
- Full Gate: `16,330 passed`, `71 skipped`.
- Full Gate coverage: statement `96.78%`, branch `96.17%`.
- Contract validation: 188 schemas, 250 examples, 217 negative examples, and
  9 OpenAPI documents.
- AE Web Node regression: `355 passed`, `0 failed`.
- Ruff and protected evidence redaction checks passed.

## Exit Decision

P8-S53 and P8.4 are closed. The Platform now has an actual PostgreSQL-backed,
admitted NSL v0.2 approval suspend/resume journey with deterministic replay,
fail-closed lineage validation, restart-safe evidence, and zero EOS write
residue. P8.5 may begin the controlled WRITE execution boundary.
