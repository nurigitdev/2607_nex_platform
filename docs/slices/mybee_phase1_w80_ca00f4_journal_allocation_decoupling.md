# W80-CA00F.4: Journal and Allocation Runtime Decoupling

## Outcome

- Stopped the installed D04 Journal controlled-write runtime at the immutable
  `PostedJournal` boundary. Journal completion no longer resolves an Allocation
  Plan, creates an AllocationBatch, refreshes Project P&L, or reports those
  accounting outcomes as completed.
- Preserved the committed Journal identity and reference in the executor result.
  A combined request may expose `FINANCE.COST_ALLOCATION.RUN` only as a deferred
  operation; it is never invoked by Journal completion.
- Added a separately callable installed accounting allocation runtime. It
  requires fresh OA `finance:allocation:execute` authority, explicit Project
  ratios, an admitted business context, a committed Journal, and the existing
  authoritative Allocation Plan resolver before it can run allocation and P&L
  refresh.
- Kept the allocation resolver, conservation/replay behavior, P&L projector, and
  EOS authoritative data path unchanged. No fixture Plan ID, ratio, Project
  count, tenant dictionary, or fallback allocation was introduced.
- Promoted intent prompt `v13`. Journal fields and one primary Project remain
  required; allocation candidates are optional, untrusted, and deferred.
  Prompt `v12` remains replay-only historical evidence.

## Contract And Persistence Fit

- `ae.business_request_context.v1` continues to require the
  `requested_allocation` field but now admits an empty array for a Journal-only
  request. Non-empty allocation records retain the existing contiguous-index,
  unique-Project, ratio-sum, and hash-bound validation.
- Primary Project attribution is still mandatory and cross-validated against the
  delegated Project. It no longer depends on the presence of allocation targets.
- No EOS, NSL, OA, WC, or WA public API changed.
- No table, column, migration, identifier, hash algorithm, or existing record was
  changed. The separate allocation runtime reuses the current allocation and
  Project P&L persistence structures.

## Verification

- Journal-only and combined-context admission, malformed allocation, Project
  identity, prompt persistence, and delegation regression coverage.
- Journal success proves zero allocation/P&L invocation and emits only the
  PostedJournal result plus an optional deferred-operation marker.
- Separate allocation success, OA denial, and missing-ratio fail-closed coverage.
- Golden A quarantine, AE coverage ownership, and MyBee runtime ownership
  inventories updated to track the active `v13` prompt and allocation runtime.
- Focused regression: `267 passed`.
- AE Slice Gate: PASS (`7002 passed`, `53 skipped`, `6/6` commands).
- AE coverage: statement `96.46%`, branch `94.72%`.
- AE product coverage: statement `97.07%`, branch `95.01%`.
- Contract validation: PASS (`277` schemas, `322` examples,
  `260` negative examples, `10` OpenAPI documents).
- Golden-journey transition, demo dependency, and AE ownership audits: PASS.

## Next Boundary

`W80-CA00F.5` must validate two independently governed installed journeys: a
Journal journey that ends at PostedJournal and IA result publication, and an
accounting-authorized allocation journey that starts from verified EOS source
data and ends at affected Project P&L refresh. The combined historical M1
journey is not the canonical acceptance path.
