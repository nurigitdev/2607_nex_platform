# MB3-01 MyBee VoucherCandidate v2 Consumer

## Status

`CLOSED` on 2026-11-12.

MB3-01 closes the MyBee-owned consumer boundary for the EOS VoucherCandidate
v2 workflow. MyBee now builds a proof-bound immutable Candidate request,
consumes authoritative EOS validation, submits the validated Candidate to the
existing scoped BUSINESS_FORMAL accounting review flow, and reads the durable
review projection.

## Implemented Boundary

- Added `mybee_ax.integrations.nex_voucher_candidate_client`.
- Added deterministic `VoucherCandidateDraft` and line admission.
- Bound every Candidate to one approved Project registration code and UUID,
  one active ApprovedDocumentEnvelope, one FL work code, and balanced lines.
- Used the canonical NSL-compatible payload hash consumed by EOS.
- Consumed only the admitted public EOS endpoints:
  - `FINANCE.VOUCHER_CANDIDATE.CREATE_V2`
  - `FINANCE.VOUCHER_CANDIDATE.VALIDATE`
  - `FINANCE.ACCOUNTING_APPROVAL.REQUEST`
  - `FINANCE.VOUCHER_CANDIDATE.REVIEW_GET`
- Extended the existing MyBee scoped-approval receipt admission to accept the
  optional EOS `candidate_review` event without relaxing the earlier receipt.
- Added a service-token HTTP transport with tenant/subject headers, bounded
  timeout, typed retryability, redacted provider failures, and strict JSON
  response admission.

## Preserved Ownership

MyBee remains a consumer. It does not import EOS service-private code, access
EOS tables, own Candidate persistence, publish directly to WC, or expose a GL
posting operation. Candidate creation, validation, review state, and outbox
lineage remain EOS-owned. Final posting still requires the later S4 controls.

No database migration was introduced by MB3-01.

## Contract And Regression Evidence

The focused MyBee contract suite passed:

```text
146 passed
```

The new consumer module's focused suite passed:

```text
87 passed
statement coverage: 100.00%
branch coverage: 100.00%
```

The test suite directly passes the MyBee request through the real EOS command
parser and compares the EOS canonical payload hash. It also covers replay,
malformed provider evidence, proof/project/document drift, review lineage,
HTTP failures, and the explicit absence of direct GL-write behavior.

The complete EOS VoucherCandidate regression passed:

```text
79 passed, 2 protected skips
```

## PostgreSQL Protected Smoke

The existing provider-owned S3-03 smoke was rerun against the actual test
database:

```text
database: postgresql://nex_eos_user@127.0.0.1:5432/nex_eos_test
tests: 1 passed, 80 deselected
```

The smoke applies the real migration chain in an isolated schema, exercises
the Candidate review state machine and immutable event guard, drops the
schema, and asserts zero residue. MB3-01 itself performs no direct database
operation.

## Slice Gate

Machine-readable evidence:

- `reports/quality/mybee_w30_mb3_01_slice_gate.json`

Result:

```text
status: PASS
commands: 6/6
tests: 573 passed, 8 protected skips
consumer statement coverage: 100.00% (threshold 96.00%)
consumer branch coverage: 100.00% (threshold 94.00%)
contract validation: PASS (239 schemas, 297 examples, 248 negative, 10 OpenAPI)
Golden Journey transition audit: PASS
demo-to-product dependency audit: PASS
```

## Repository Full Gate

The W30 closure Full Gate passed:

```text
status: PASS
tests: 21,534 passed, 157 skipped
statement coverage: 96.74% (threshold 96.00%)
branch coverage: 95.93% (threshold 94.00%)
product statement/branch coverage: 98.55% / 97.13%
harness statement/branch coverage: 94.18% / 92.95%
Node tests: 374 passed
Vitest: 130 passed across 29 files
contract validation: PASS
Golden Journey audit: PASS
dependency audit: PASS
browser typecheck/build/cutover acceptance: PASS
```

## Next Entry

W30 is closed after the Repository Full Gate passes. The next planned entry is
W40 `S4-01`, where fresh accounting Human SoD proof and current OA authority
must be admitted before atomic posting. MB3-01 does not grant that authority.
