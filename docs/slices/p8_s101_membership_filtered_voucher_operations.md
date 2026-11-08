# P8-S101: Membership-Filtered Voucher Operations

## Scope

P8-S101 closes canonical Voucher Draft CREATE/GET/LIST admission around the
EOS-owned Project membership boundary.

- Voucher CREATE keeps its existing controlled-WRITE, approval, idempotency,
  and BusinessOperation path. The mutation transaction now also requires an
  active Project and an active `OWNER`, `MANAGER`, or `MEMBER` membership for
  the requester.
- `FINANCE.VOUCHER_DRAFT.GET` and `FINANCE.VOUCHER_DRAFT.LIST` require current
  OA `finance:voucher-draft:read` authority and independently filter at the
  EOS query boundary by active tenant-scoped Project membership.
- A finance auditor bypass is available only through the explicit
  `finance:voucher-draft:audit` scope. It does not weaken tenant or active
  Project isolation.
- LIST requires an exact Project ID, uses bounded `limit`/`offset`, and orders
  results deterministically by transaction date, creation time, and Voucher
  ID.

No database migration, direct cross-service database read, or model-selected
stable authority was added.

## NSL Admission

The canonical read Skills are source-admitted from NSL revision
`2b88f2f8d097a0aa121e01db5290a650f15b10c8`:

- `FINANCE.VOUCHER_DRAFT.GET` `1.0.0`
- `FINANCE.VOUCHER_DRAFT.LIST` `1.0.0`

Artifact manifest SHA-256:

```text
sha256:3d4223990993e7d2b634d746cde5b89cc9335c266717bcb055db863590b428a9
```

The independently admitted runtime remains NSL `0.2.1`, source revision
`d53658ec...`, wheel SHA-256 `a89ce5fd...`. Exact source, source hashes,
semantic hashes, manifest identity, operation registry, and EOS route IDs are
checked by the protected source test.

## Contracts

- `nsl_voucher_read_artifact_admission.v1.schema.json`
- `nsl_voucher_read_artifact_admission.pass.json`
- `voucher_draft_list_request.v1.schema.json`
- `eos_voucher_draft_list_request.project_scoped.json`
- Canonical EOS OpenAPI GET/LIST operation IDs

## Verification

- Focused Voucher/Project regression: `65 passed`, one expected source guard
  skip; protected actual-source re-run: `2 passed`, no skip.
- Contract validation: `197 schemas`, `261 examples`, `224 negative examples`,
  and `9 OpenAPI` documents.
- EOS Slice Gate: `674 passed`, `21` expected protected skips.
- EOS statement coverage: `98.85%`; branch coverage: `98.15%`.
- New `voucher_access.py`: statement `100%`; branch `100%`.
- Checkpoint Gate: `16,641 passed`, `115` expected protected skips;
  statement `98.67%`, branch `97.15%`; contract validation remained
  `197/261/224` with `9` OpenAPI documents.

The protected skips are historical PostgreSQL/object-store profiles not
claimed by this Slice. P8-S102 owns the actual OA/AE/WC/EOS PostgreSQL, live
generation, and authenticated Playwright journey.

## Exit

P8-S101 closes membership-filtered Voucher admission and read operations.
Its required Checkpoint Gate must pass before P8-S102 begins the protected
multi-service demonstration journey.
