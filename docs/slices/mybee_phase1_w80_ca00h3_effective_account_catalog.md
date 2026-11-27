# W80-CA00H.3 Effective K-IFRS Account Catalog Facade and Selector

## Status

IMPLEMENTED / CHECKPOINT GATE PASSED

## Product Boundary

- EOS remains the sole authority for effective company account catalogs and
  PostingRule admission.
- AE exposes an authenticated user facade and uses signed service trust for the
  EOS internal read.
- The facade checks company/effective-date response identity, filters to
  postable-leaf accounts admitted for the transaction currency, and removes
  internal account IDs and policy evidence from the browser projection.
- AE Web displays the authoritative account name first and code second.
- Voucher create and revision commands continue to carry only `account_code`;
  display names never become accounting identity.
- A missing, malformed, stale, or unavailable catalog fails closed. No Web
  fallback list, default expense account, or tenant dictionary was added.

## Implementation

- Added protected `GET /api/v1/business-account-catalog` to the existing AE
  business voucher facade.
- Added the versioned `ae_business_account_catalog.v1` browser projection.
- Added an AE Web catalog client and installed-runtime registration.
- Added `company_id` to the existing EOS VoucherCandidate projection so the
  effective catalog can be resolved without browser inference or new storage.
- Replaced free-text account-code fields in voucher create/review with
  authoritative selectors while retaining immutable code-only writes.
- Added malformed response, authority drift, currency/postable filtering,
  client parsing, selector, and immutable revision tests.

## Verification

- Focused Python regression: `31 passed` across AE facade and EOS composition.
- Focused React/client regression: `9 passed`.
- AE Web TypeScript check: passed.
- NeX-AE-API Slice Gate: `7163 passed`, `57 skipped`; statement `96.42%`,
  branch `94.60%`; AE ownership audit passed.
- NeX-EOS Slice Gate: `2440 passed`, `69 skipped`; statement `96.37%`, branch
  `94.19%`.
- NeX-AE-Web Slice Gate: `297 passed`; statement `97.78%`, branch `97.28%`.
- Repository Checkpoint Gate: `23576 passed`, `198 skipped`; statement
  `98.12%`, branch `96.54%`.
- Contract validation, transition audit, and demo/product dependency audit:
  passed.

Actual cross-service PostgreSQL and authenticated Playwright evidence remain
owned by `W80-CA00H.5`. No remote model provider is required for this Slice.
