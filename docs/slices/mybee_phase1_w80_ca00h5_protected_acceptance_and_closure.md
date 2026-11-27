# W80-CA00H.5 Protected PostgreSQL, Playwright, and Repository Closure

## Status

COMPLETE / PROTECTED MATRIX PASSED / REPOSITORY FULL GATE PASSED

## Closure Boundary

W80-CA00H.5 closes the proposal and VoucherCandidate review-usability
amendment without adding a database migration, queue, authority source, or
browser-owned accounting rule. The installed acceptance reuses the canonical
W80-CA00G.7 journey runner and extends it to prove the W80-CA00H presentation
contracts against authoritative EOS, WC, OA, and AE state.

The accepted product behavior is:

- proposal approval lines precede editable proposal fields and are invalidated
  by revision changes;
- BUSINESS_FORMAL rejection reasons are mandatory at the protected boundary
  and are visible to the requester on terminal rejection;
- VoucherCandidate Project Codes come only from the approved envelope;
- effective account names and codes come from the EOS company catalog while
  writes retain canonical `account_code` identity;
- accounting BUSINESS_FORMAL and NSL_WRITE reviews display the exact balanced
  Candidate revision as a voucher-shaped document;
- unavailable or malformed authority remains a typed unavailable state and is
  never reconstructed from display text.

## Protected Installed Acceptance

The protected matrix ran on product revision `42752750d41f` with actual Docker
Compose, all eight admitted PostgreSQL test databases, OpenBao, RustFS, the
canonical Qwen3.8-Flash-Next generation provider, and authenticated Playwright.
It passed six independent journeys:

1. one-stage business approval;
2. two-stage business approval;
3. three-stage approval through accounting and governed WRITE;
4. middle-stage business rejection;
5. final-stage business rejection;
6. accounting rejection, revision correction, resubmission, and commit.

The authoritative residue checks reported:

- 6 proposals: 4 approved and 2 rejected;
- 4 VoucherCandidates and 7 immutable Candidate revisions;
- 2 immutable Journals;
- 24 append-only product checkpoints;
- zero duplicate pending authorities;
- zero pending AE runtime, WC delivery, or EOS outbox rows after restart;
- zero product residue after cleanup.

Playwright captured 39 PNGs and 6 screen manifests. Both successful accounting
paths showed balanced two-line documents for BUSINESS_FORMAL and NSL_WRITE;
the correction path moved from Candidate revision 2 to revision 3 and projected
only the latest admitted revision. Rejected business paths created no voucher.

Canonical evidence:

- `reports/deployment/mybee-w80-ca00g7-protected-matrix.json`
- `reports/deployment/mybee-w80-ca00g7-browser-evidence.json`
- `reports/deployment/mybee-w70-m1-diagnostic-evidence/mybee-w80-ca00g7-20261127T022817Z-64c8d0c1/`

The diagnostic package contains 70 files and intentionally includes the raw
prompt, AgentPlan, and ExecutablePlan under the approved DEBUG evidence
boundary. It contains no service token or unredacted secret value.

## Live Defects Closed

The protected run exposed and closed three integration defects that focused
tests did not reveal:

- the approval fetch adapter normalized away a valid `accounting_document`;
- a selected pending gate could retain an `UNAVAILABLE` projection after EOS
  authority became readable;
- a single transient browser fetch failure could abort an otherwise healthy
  long protected matrix.

The fixes preserve strict schema admission, refresh only selected unavailable
accounting projections, invalidate the detail/projection cache when a gate is
opened, and retry only the browser's bounded `Failed to fetch` transport case.
Hard HTTP and contract failures remain fail-closed.

## Gate Evidence

Checkpoint after W80-CA00H.3:

- Python: `23,576 passed`, `198 skipped`;
- statement coverage: `98.12%`;
- branch coverage: `96.54%`.

Final Repository Full Gate:

- Python: `24,313 passed`, `199 skipped`;
- repository statement coverage: `96.10%` against `96.00%`;
- repository branch coverage: `94.91%` against `94.00%`;
- product statement/branch coverage: `98.09% / 96.48%`;
- harness statement/branch coverage: `93.57% / 91.62%`;
- schema/example/negative/OpenAPI contracts: `280 / 322 / 260 / 10`;
- Node contracts: `409 passed`;
- React: `166 passed` across 36 files;
- TypeScript, production build, production cutover acceptance, and full Web
  acceptance all passed;
- full Web acceptance: 6 journeys, 71 checks, and 16 screenshots.

The first Full Gate attempt correctly detected that the new AE-to-EOS approval
facade endpoint had not been admitted to the S141 exact loopback inventory. The
inventory was updated from 54 to 55 occurrences across the same 34 files, and
the S141 nine-audit closure passed. A later React full-suite run exposed a
one-second asynchronous test budget under aggregate load; the proposal test now
uses an explicit five-second render budget, while the focused and full React
suites both pass.

## Decision

W80-CA00H.1 through W80-CA00H.5 are COMPLETE. The proposal/voucher usability
and accounting-presentation amendment is admitted for the installed product
baseline. Remaining Starlette/httpx deprecation and frontend bundle-size
warnings stay in the existing compatibility/performance backlog and are not
release blockers for this amendment.
