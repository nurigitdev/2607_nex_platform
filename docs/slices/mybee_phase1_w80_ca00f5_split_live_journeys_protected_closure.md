# W80-CA00F.5: Split Live Journeys and Protected Closure

## Outcome

- Status: `CLOSED`
- Product source head: `46aadc52116b3df960110d5e7f1f445ff3bed40d`
- The installed Journal and accounting-allocation journeys passed independently.
- Journal completion stopped before allocation and published its own requester
  result. Allocation entered through its separate typed WorkIntent, authority,
  Product Coordinator, RuntimeJob, and result-publication path.
- The closure added no database migration, business fixture, scenario branch,
  fixed ratio, fixed Project count, or tenant-specific runtime mapping.

## Protected Live Acceptance

The exact-head runner used actual OA, AE, WC, EOS, and WA PostgreSQL; installed
Compose services; OpenBao; RustFS; the remote generation provider; and
authenticated Playwright.

| Evidence | Result |
| --- | --- |
| Protected runner | `PASS` |
| Generation model | `Qwen3.8-Flash-Next` |
| Immutable model revision | `hf:fc694b54fb0174e0913e6adf86691ef85a4ead47` |
| Journal request to IA result | `47.001 s` |
| Allocation request to IA result | `19.043 s` |
| PostgreSQL identities | `8/8 ADMITTED`, migrations `CURRENT` |
| Isolated migration inventory | `210` migrations across eight databases |
| Restart recovery | both results recovered; result hashes stable |
| Cleanup | eight isolated schemas dropped; zero residue |
| Secrets | forbidden and absent from the result artifact |

The live database state contained two executions and two acknowledged
Workspace results. It contained one VoucherCandidate, one immutable Journal,
one AllocationBatch, two AllocationLines, and two affected-Project P&L
projections. The allocation conserved `13,502,000` with zero unallocated
amount. Restart and replay retained the same counts and result hashes.

WA admitted the execution evidence independently. Its evidence/asset records
are source references and execution records; they do not duplicate the EOS
VoucherCandidate, Journal header/lines, AllocationBatch, or P&L truth.

## Acceptance Matrix

| # | Requirement | Result | Evidence |
| ---: | --- | --- | --- |
| 1 | Only business approval is initially actionable | PASS | Journal Playwright showed the first `BUSINESS_FORMAL` decision before any accounting decision; sequential-stage regression passed. |
| 2 | Accounting activates only after business approval | PASS | Journal screen order was business, accounting, then `NSL_WRITE`; three sequential decisions were persisted. |
| 3 | Business rejection creates no accounting or WRITE gate | PASS | EOS rejection and stage-publication regression in the focused closure suite. |
| 4 | Accounting rejection creates no Journal mutation | PASS | Transactional rejection and controlled-write rejection regression; immutable Journal count remains zero on rejection paths. |
| 5 | Replay, restart, and ACK loss create no parallel stage | PASS | Approval replay/ACK-loss regression plus post-restart result/hash and database-count stability. |
| 6 | Journal result is requester-visible without waiting for WA settlement | PASS | Existing Workspace commit-before-best-effort-WA tests and live Journal result rendering. |
| 7 | WA outage/retry cannot remove or duplicate the IA result | PASS | WA-unavailable regression and exact post-restart count of one Journal AgentResult. |
| 8 | WA stores evidence/references, not duplicate accounting truth | PASS | WA admission contract regression and live EOS/WA count separation. |
| 9 | Optional artifact retention follows visibility and explicit policy | PASS | WA intake/asset classification regression; no Journal payload is promoted as an optional WA business asset. |
| 10 | Journal journey creates no AllocationBatch or P&L refresh | PASS | Live `journal_stopped_before_allocation=true`; allocation counts appeared only after the second journey. |
| 11 | Unauthorized allocation cannot execute | PASS | Fresh OA allocation-authority and denial regression; allocation live path used the accounting subject. |
| 12 | Authorized allocation uses EOS authority and conserves amounts | PASS | One authoritative plan, two EOS Project lines, exact amount conservation, zero residual, and two affected projections. |
| 13 | Exact replay creates no duplicate business/result/evidence record | PASS | One Journal, one AllocationBatch, two independent AgentResults, stable hashes, and successful restart/replay checks. |
| 14 | Product runtime contains no scenario fixture or fixed business value | PASS | Live residue list empty, post-request business mutation count zero, and product-entry residue guards passed. |
| 15 | Both journeys pass independently on exact head | PASS | Journal and allocation Playwright modes each returned `PASS` with distinct interactions and results. |

Acceptance result: `15/15 PASS`.

## Regression and Full Gate

The parent closure focused suite completed with `336 passed`, `2 skipped`.
The skipped cases are opt-in PostgreSQL smoke tests whose protected boundaries
were exercised by the actual eight-database live run above.

The existing exact-head Repository Full Gate remains valid because this Slice
changed no product source after it ran:

- Python: `24,111 passed`, `195 skipped`
- statement coverage: `96.23%`
- branch coverage: `95.12%`
- Node: `401 passed`
- React/Vitest: `134 passed`
- result: `PASS`

## Evidence Index

- Live result:
  `reports/deployment/mybee-w80-ca00f5-split-live-journeys.json`
- Stage timing:
  `reports/deployment/mybee-w80-ca00f5-stage-timings.json`
- Restricted diagnostic session:
  `reports/deployment/mybee-w70-m1-diagnostic-evidence/mybee-w80-ca00f5-20261125T085606Z-3466be68`
- Diagnostic manifest hash:
  `6c1b7f5a9bfc149557d1ff87de70a04aecdc3311c4b34e4019ca2e04044a5612`
- Evidence inventory: 40 files, four screen manifests, and 11 screenshots;
  raw prompt, AgentPlan, and ExecutablePlan evidence admitted under the
  restricted live-journey policy.

## Closure Decision

`W80-CA00F.5` and its parent `W80-CA00F` are closed. Journal approval/posting,
requester result publication, WA execution evidence, and accounting allocation
now have separate product responsibilities while retaining the common Agent,
WC, RuntimeJob, EOS authority, and result-publication foundations.
