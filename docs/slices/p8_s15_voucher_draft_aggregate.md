# P8-S15: VoucherDraft Aggregate Foundation

Completed on 2026-10-21. NeX-EOS now persists a balanced VoucherDraft and its
canonical lines as one database transaction, without exposing an external
WRITE API.

## Scope

- Added migration `2506_eos_voucher_draft` with `eos_voucher_draft` and
  `eos_voucher_draft_line`.
- Added tenant-scoped stable Project, requester, source, and Account refs.
- Added deterministic line numbering, economic category, and evidence refs.
- Accepted only finite, non-zero `Decimal(20,2)` signed amounts and required
  their exact sum to be zero.
- Revalidated Project and every Account against tenant, status, and transaction
  date inside the same unit of work before aggregate insertion.
- Kept the initial lifecycle state fixed to `DRAFT` and version fixed to 1.

Binary floating-point and display-name-only Project/Account authority are not
accepted. This Slice creates a draft business object only; approval, posting,
and external mutation routes remain later P8 work.

## Verification

- Focused VoucherDraft regression: 37 passed with 100% statement and branch
  coverage for `vouchers.py`.
- Actual dev/test PostgreSQL migrations applied `2506`.
- Protected PostgreSQL smoke connected as `nex_eos_user@nex_eos_test`, created
  and reread a balanced two-line draft transaction, and left zero residue.
- EOS Slice Gate: 183 passed, 8 protected skips.
- EOS statement coverage: 99.66%; branch coverage: 100%.
- Contract validation: 174 schemas, 236 examples, 204 negative examples, and
  9 OpenAPI documents.
- Remote model providers were not required.
