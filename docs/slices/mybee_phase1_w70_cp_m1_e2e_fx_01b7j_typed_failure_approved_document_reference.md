# CP-M1-E2E-FX-01B.7J: Typed Product Resume Failure Diagnostics and ApprovedDocument Receipt/Reference Closure

## Status

- Date: `2026-11-20`
- Status: `SOURCE AND POSTGRESQL VERIFIED`; protected installed live replay pending
- Parent boundary: `CP-M1-E2E-FX-01B.7`
- Database migration: none
- Public API or persisted schema change: none
- Remote provider: required only for the final protected installed journey

## Failure Reconciliation

The `.7I` protected journey delivered an approved BUSINESS_FORMAL event and
queued the generalized Product resume job, but that job failed with only
`ae.product_coordinator_assignment_failed`. Source inspection found that the
MyBee EOS consumers exposed their typed failure as `code`, while the Product
Runtime accepted only `error_code`. The specific EOS denial was therefore
discarded at the RuntimeJob settlement boundary.

The installed acceptance requester also lacked the
`finance:document:read` scope required by the protected ApprovedDocument GET.
This explains the observed post-approval failure without weakening EOS
authorization: a requester whose scope is missing or revoked must still fail
closed during resume.

The ApprovedDocument identity itself remains the immutable `envelope_id`.
Neither the scoped approval `case_id`, the WC work-item identity, nor the final
business approval proof is a valid replacement for this resource reference.

## Decision

- MyBee consumer exceptions expose canonical `error_code` and retain `code`
  for compatibility.
- Product boundaries admit bounded codes from `error_code` or legacy `code`;
  malformed values are redacted to the generic Product failure reference.
- RuntimeJob settlement stores only the typed code and never the protected
  upstream detail.
- Approved DOCUMENT_SIGNOFF receipts must carry a canonical UUID
  `approved_document_envelope.envelope_id`.
- BUSINESS_FORMAL resume validates that envelope reference before any EOS
  ApprovedDocument read.
- The installed requester seed includes `finance:document:read`; runtime
  revocation and missing-scope denial remain authoritative EOS outcomes.
- EOS/WC terminal diagnostics accept the two valid observation windows:
  WC may be one version ahead before EOS ingests the decision, or equal after
  ingestion. Terminal target role is recovered from the immutable approval
  policy stage when the completed EOS case clears its active role.

## Implementation

- Added compatibility-safe typed Product error extraction and strict code
  syntax admission.
- Added canonical ApprovedDocument envelope validation at receipt admission
  and Product coordinator resume.
- Added the missing installed acceptance read scope without changing product
  authorization policy.
- Corrected bounded EOS/WC approval diagnostics for pending and terminal
  observations.
- Reconciled two historical MyBee test receipts with the canonical WC
  `approval_work_item_id` requirement; product receipt validation was not
  relaxed.

## Verification

- Ruff: `PASS`
- diff validation: `PASS`
- focused Product, approval receipt, MyBee consumer, and acceptance regression:
  `259 passed`
- ApprovedDocument canonical/noncanonical focused regression: `57 passed`
- actual `nex_ae_test` PostgreSQL RuntimeJob settlement smoke: `2 passed`
  - migrations applied to the current repository head;
  - isolated schema created and removed;
  - no remote provider contacted.
- AE Slice Gate: `PASS`
  - tests: `6878 passed`, `53 skipped`;
  - statement coverage: `96.46%`;
  - branch coverage: `94.72%`;
  - product statement coverage: `97.08%`;
  - product branch coverage: `95.02%`;
  - contract validation, transition audit, dependency audit, and ownership
    checks: `PASS`;
  - commands: `6/6`.

## Protected Live Rule

The next exact-head installed replay must prove all of the following:

1. the approved DOCUMENT_SIGNOFF event carries the exact immutable envelope;
2. the requester can read that envelope with fresh OA authority;
3. a missing or revoked read scope persists
   `EOS_APPROVED_DOCUMENT_AUTHORIZATION_DENIED`, not a generic Product error;
4. approval case, proof, and envelope identities never substitute for one
   another;
5. WC/EOS diagnostics report valid pending or terminal bindings without a
   false role/version failure;
6. the Product resume advances beyond `WAITING_BUSINESS_APPROVAL` without
   weakening replay, restart, ACK-loss, lease, or zero-residue guarantees.

The protected live journey must not start until DGX availability is confirmed.

