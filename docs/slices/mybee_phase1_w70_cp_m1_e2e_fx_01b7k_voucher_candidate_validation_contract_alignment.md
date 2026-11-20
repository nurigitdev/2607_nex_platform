# CP-M1-E2E-FX-01B.7K: EOS VoucherCandidate Validation Contract Alignment

## Status

- Date: `2026-11-20`
- Status: `SOURCE AND GATES VERIFIED`; exact-head installed replay pending
- Parent boundary: `CP-M1-E2E-FX-01B.7`
- Database migration: none
- Public API or persisted schema change: none
- Remote provider: not required for the corrective Slice Gate

## Live Failure Reconciliation

The exact-head protected installed journey reached approved-document lookup,
VoucherCandidate creation, and EOS validation successfully. EOS returned HTTP
`200` with a canonical `eos_voucher_candidate_validation.v1` projection, but
the MyBee consumer rejected it as `MYBEE_CANDIDATE_VALIDATION_INVALID` before
the accounting approval request could be created.

The canonical schema and EOS producer both require and emit
`accounting_rule_profile_hash`. The MyBee consumer's exact-field allowlist was
missing that field. The live failure was therefore a producer-consumer
contract drift, not a provider, approval, database, or fixture failure.

## Decision

1. Keep `eos_voucher_candidate_validation.v1` unchanged. It is already the
   canonical contract and its additional-properties boundary remains closed.
2. Admit `accounting_rule_profile_hash` as a required SHA-256 hash in the
   MyBee VoucherCandidate consumer.
3. Preserve the value in the admitted immutable validation projection. The
   existing `validation_hash` binds it into downstream accounting review and
   EOS revalidation; no accounting-review schema expansion is required.
4. Add a source-backed inventory test that compares the consumer allowlist to
   the canonical JSON Schema required fields.
5. Continue to reject missing, malformed, or unexpected validation fields.

## Scope

- MyBee VoucherCandidate validation consumer contract
- canonical schema inventory regression
- malformed and missing accounting-rule-profile hash branches
- existing create, validate, review, replay, and HTTP transport regression

## Non-Goals

- no EOS producer change
- no OpenAPI or schema version change
- no database migration
- no accounting-review v4 contract
- no live journey replay until the focused and Slice Gates pass

## Verification

- Ruff format and lint: `PASS`
- focused MyBee consumer and EOS validation regression: `207 passed`, `6`
  protected skips
- M1 Product preparation, approval receipt, resume, router, and RuntimeJob
  settlement regression: `231 passed`, `2` protected skips
- actual `nex_ae_test` PostgreSQL protected smoke: `3 passed`
  - current migrations applied in isolated schemas;
  - ApprovedDocument receipt replay and Product resume settlement passed;
  - isolated schemas were removed after each run.
- AE Slice Gate: `PASS`
  - tests: `6878 passed`, `53 skipped`;
  - statement coverage: `96.46%`;
  - branch coverage: `94.72%`;
  - product statement coverage: `97.08%`;
  - product branch coverage: `95.02%`;
  - contract validation, transition audit, dependency audit, and ownership
    checks: `PASS`;
  - commands: `6/6`.

## Exact-Head Replay Rule

The protected installed journey may resume only from a clean commit containing
this contract alignment. It must prove that the EOS HTTP `200/PASS` validation
projection is admitted with its exact `accounting_rule_profile_hash`, the
accounting approval request is created, and no
`MYBEE_CANDIDATE_VALIDATION_INVALID` attempt remains. A later failure must be
reported as a separate typed boundary; it must not weaken this strict contract.
