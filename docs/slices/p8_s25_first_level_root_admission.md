# P8-S25 First-Level Depth and Root Admission

## Scope

Activate first-level Delegation Guard lineage for the NeX-WC runtime while
preserving direct P7 service construction as an explicit compatibility mode.

## Admission Semantics

- first Agent delegation has depth `1`
- `root_work_item_id` equals the admitted WorkItem identity
- parent WorkItem and parent Claim authority are null
- the admitted policy reference and semantic hash are persisted
- WorkItem and lineage insertion share one repository lock or DB transaction
- idempotent replay returns the original WorkItem and does not create a second
  lineage row
- OA `work:delegate` authority is freshly checked before every replay

## Compatibility

- `WorkItemService` defaults to P7 compatibility when constructed directly
- the actual NeX-WC composition enables the Delegation Guard
- historical P7 WorkItems are not backfilled implicitly

## Verification

- focused S24/S25 regression: `36 passed`
- P7/WC compatibility regression: `310 passed, 8 protected skips`
- changed-module statement coverage: `98.03%`
- changed-module branch coverage: `97.58%`
- Python compile and whitespace validation: pass

Actual PostgreSQL activation remains reserved for P8-S31. The SQL repository
tests prove that WorkItem and lineage admission share one session and commit
boundary; the final protected gate will prove the same behavior against
`nex_wc_test`.
