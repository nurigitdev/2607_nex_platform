# CP-M1-E2E-FX-01B.7E: Expired Claim Recovery, Product Wait State, and Approver Inbox Delivery Closure

## Status

- Date: `2026-11-19`
- Status: `CLOSED`
- Parent boundary: `CP-M1-E2E-FX-01B.7`
- Database migration: none
- Remote provider: not required
- Next boundary: protected exact-head `CP-M1-E2E-FX-01B.7` live replay

## Failure Reconciliation

The `.7D-A` live run did not expose one missing transport. It exposed three
separate state and authority defects:

1. the WC assignment dispatcher scanned only `CREATED` and `ROUTED` WorkItems,
   so an expired claim whose handoff had never reached AE could remain
   `ASSIGNED` indefinitely;
2. a successfully admitted Product coordination execution remained projected
   as `QUEUED:INTAKE` even though it was durably waiting for BUSINESS_FORMAL
   approval; and
3. the acceptance approval policy targeted `TEAM_LEAD`, while the admitted OA
   approver roles omitted that exact role, so WC correctly filtered the
   approval out of that user's inbox.

Approval delivery was already structurally present:

```text
EOS BUSINESS_FORMAL approval
  -> WC approval SoR and role/subject authorization
  -> AE authenticated approval facade
  -> approver's AE Web approval inbox
```

The approval is not copied into an IA conversation. The authenticated approval
inbox is the canonical user-delivery surface; IA may link to or summarize that
surface later without becoming a second approval SoR.

## Recovery Contract

The existing WC assignment dispatcher now scans one additional bounded source:
expired, active claims attached to `ASSIGNED` WorkItems. Automatic reclaim is
admitted only when all of the following hold:

- the active claim lease is expired at the scan observation time;
- the active assignment has no `agent_execution_id`;
- the matching `CLAIM_EXECUTION_HANDOFF` outbox is `PENDING` or `FAILED`; and
- the WorkItem remains at the exact expected version.

The existing `WorkCoordinationService.claim()` authority performs the reclaim.
It expires generation N, releases its assignment, fails the stale handoff, and
creates generation N+1 with a new lease and handoff in one existing repository
transaction. No second recovery service or persistence model was introduced.

An `ENQUEUED` handoff, a delivered handoff, or an assignment already bound to
an AE execution is never reclaimed by this scan. Those states may represent a
durable PA execution or approval checkpoint; reclaiming them could create a
duplicate execution. Their later lease/renewal lifecycle remains a separate
explicit design boundary.

## Product Execution and Approval Visibility

Installed Product claim admission now transitions the durable AE execution to
`WAITING_APPROVAL:PLAN_BUILD` after Product coordination starts. Exact replay
returns the same state without another transition, and terminal or missing
executions fail closed. A normal runtime step is still not scheduled until the
approval event resumes preparation.

The M1 acceptance authority seed, EOS organization position, and approval
policy now share one `TEAM_LEAD` role constant. The approver therefore satisfies
the same role used by WC target filtering. This is acceptance authority
alignment, not a tenant-, Project-, or scenario-specific product branch.

## Verification

- focused AE/WC regression including actual WC PostgreSQL: `82 passed`
- actual database: `nex_wc_test`
- PostgreSQL recovery: generation 1 `EXPIRED`, generation 2 `ACTIVE`
- protected tenant cleanup and independent residue check: `0`
- WC Slice Gate: `753 passed`, `20` protected skips
  - statement coverage: `98.29%`
  - branch coverage: `95.76%`
  - commands: `5/5`
- AE Slice Gate: `6834 passed`, `51` protected skips
  - statement coverage: `96.40%`
  - branch coverage: `94.64%`
  - active Product coverage: statement `97.02%`, branch `94.94%`
  - commands: `6/6`
- contract validation, Golden Journey transition audit, demo/product
  dependency audit, and AE ownership audit: `PASS`
- Ruff, compile, and diff checks: `PASS`
- evidence:
  - `reports/quality/mybee-w70-cp-m1-01b7e-wc-slice-gate.coverage.json`
  - `reports/quality/mybee-w70-cp-m1-01b7e-ae-slice-gate.coverage.json`

## Closure

The expired unbound claim and orphaned Product execution observability gaps are
closed without a migration or remote-provider call. The approval path remains
WC-owned and is visible through the authenticated AE approval inbox with exact
OA role matching. The next admitted action is one protected exact-head live
journey; DGX availability must be confirmed immediately before that run.
