# MyBee Phase 1 S3-01 VoucherCandidate v2 Immutable Revision/Line

## Status

- Slice: `S3-01`
- Status: implemented and verified
- EOS migration: `2534_eos_voucher_candidate_v2.sql`
- Remote model providers: not required

## Boundary Decision

`VoucherCandidate v2` is a new Project-specific accounting candidate. It does
not retrofit the historical `VoucherDraft v1` schema. Every candidate binds
the following immutable lineage:

```text
ACTIVE approved Project UUID + registration code
  -> ACTIVE ApprovedDocumentEnvelope v2
  -> VoucherCandidate header
  -> immutable revision 1
  -> immutable debit/credit lines
```

The user-facing Project registration code is stored with the internal Project
UUID on the header and every line. A request code, legacy direct Project,
inactive Project, expired/revoked document, mismatched UUID/code pair, or
unapproved account fails closed before candidate persistence.

## Persistence And Immutability

Migration 2534 adds:

- `eos_voucher_candidate` for tenant-scoped identity and workflow state;
- `eos_voucher_candidate_revision` for hash-bound revision evidence;
- `eos_voucher_candidate_line` for balanced-side accounting candidates.

Candidate revision and line rows are append-only. PostgreSQL triggers reject
`UPDATE` and `DELETE`. Candidate business identity fields are immutable while
the header reserves explicit workflow fields for later S3 transitions. Table,
constraint, and index names remain within PostgreSQL identifier limits.

## Command And API

- Operation: `FINANCE.VOUCHER_CANDIDATE.CREATE_V2`
- Scope: `finance:voucher-candidate:create`
- POST: `/internal/v2/finance/voucher-candidates`
- GET: `/internal/v2/finance/voucher-candidates/{candidate_id}`

Creation uses the existing EOS business-operation coordinator, canonical NSL
WRITE payload hash, idempotency key, transactional outbox, fresh OA effective
authorization, and exact Project/document/account admission. Replays return
the original candidate and revision without creating new identities or rows.
Service-token denial, missing dependencies, malformed commands, authorization
denial, conflicts, and persistence failures retain typed fail-closed errors.

## Compatibility

- VoucherDraft v1 routes, tables, and projections remain unchanged.
- Existing EOS event and transaction infrastructure is reused.
- OpenAPI, JSON Schema, positive example, and negative missing-Project-code
  example are additive.
- No CX/MO provider or generation runtime is required for this Slice.

## Verification

NeX-EOS Slice Gate:

```text
status: PASS
commands: 6/6
tests: 1,397 passed, 43 skipped
statement coverage: 96.43% (threshold 94.00%)
branch coverage: 94.44% (threshold 94.00%)
authorization.py: statement/branch 100%/100%
finance_v2_api.py: statement/branch 100%/100%
voucher_candidate_commands.py: statement/branch 100%/100%
voucher_candidates.py: statement/branch 96.57%/94.44%
contract validation: PASS (235 schemas, 293 examples, 246 negative, 10 OpenAPI)
Golden Journey transition audit: PASS
demo-to-product dependency audit: PASS
```

Machine-readable evidence:

- `reports/quality/mybee_w30_s3_01_slice_gate.json`

Actual `nex_eos_test` protected smoke:

- applied all EOS migrations through 2534 in an isolated schema;
- created and idempotently replayed one Project-specific VoucherCandidate;
- PostgreSQL rejected revision and line mutation through immutable triggers;
- dropped the isolated schema and verified zero residue.

## Next Entry

S3-02 may add candidate validation and review state transitions while keeping
revision and line evidence append-only. It must consume this Project,
ApprovedDocument, authorization, canonical-hash, and replay boundary without
falling back to VoucherDraft v1 semantics.
