# W80-CA00F.4A: Independent Accounting Allocation Authority Lineage Closure

## Outcome

- Added `ae.accounting_allocation_work_intent.v1`, a typed and semantic-hash
  bound allocation intent that identifies the tenant, company, requester,
  execution, source Journal line, source kind, Project-code ratio set, and
  requester-visible publication target.
- Added `ae.accounting_allocation_authority.v1`. It records a fresh OA
  `finance:allocation:execute` revision and evaluation time and binds them to
  one separately scheduled RuntimeJob, WorkIntent hash, replay identity, and
  IA or accounting Workspace target.
- Introduced the code-based EOS resolver contract
  `eos_cost_allocation_plan_resolve.v2`. The caller no longer supplies Project
  UUIDs. EOS resolves every requested code to exactly one ACTIVE Project and
  one current APPROVED company binding before selecting an exact approved
  AllocationPlan.
- Kept the signed D04/D12 release's full-file OpenAPI digest unchanged. The v2
  request/response JSON schemas are admitted as a backward-compatible internal
  resolver extension; promoting them as the sole OpenAPI component requires a
  separately signed Skill release and belongs to the W80-CA00F.5 activation
  boundary.
- Added `mybee.approved_allocation_plan_authority.v2`. It binds the independent
  accounting authority hash, verified SourcePool, selected plan, and the
  EOS-resolved Project IDs/codes/ratios. No default ratio, fixed Project count,
  tenant dictionary, fallback Plan, fixture, or M1 business value is admitted.
- Kept the v1 UUID resolver and D04 preparation lineage for explicit historical
  replay only. New execution does not read `READY_FOR_D04`.
- Gave the independent path a scenario-neutral
  `mybee.accounting-allocation-financial-result.v1` result identity while
  preserving `mybee.m1-financial-result.v1` for historical replay.

## Persistence And Runtime Fit

- No database migration or new table was added.
- EOS reuses `eos_project`, `eos_project_company_binding`,
  `eos_cost_allocation_plan`, allocation batch/reconciliation, and Project P&L
  tables.
- AE binds the independent execution to existing RuntimeJob identity and the
  normal result publication lineage. The returned product result carries the
  RuntimeJob reference, replay identity, authority hash, and publication target
  required by the standard AgentResult/WorkspaceResult finalization boundary.
- An existing checkpoint is accepted only for exact semantic replay. A changed
  OA revision, RuntimeJob dedup identity, WorkIntent, Project ratio, or
  publication target fails closed.

## Security And Authority Rules

1. OA is queried at execution time; inactive, wrong-tenant, wrong-subject, or
   missing-scope responses are denied.
2. RuntimeJob execution identity must equal the WorkIntent execution identity.
3. Project codes and ratios are canonicalized, unique, and total exactly one.
4. EOS rejects missing, inactive, cross-company, expired, revoked, or ambiguous
   Project authority.
5. AllocationPlan resolution remains read-only and exact; nearest-plan fallback
   is prohibited.
6. SourcePool kind and effective date must agree with the admitted WorkIntent.

## Verification

- Focused AE, MyBee, EOS allocation/plan/P&L regression: PASS.
- Independent intent, OA denial, RuntimeJob drift, exact replay, publication,
  code-only resolution, Project authority, and historical compatibility branch
  coverage: PASS.
- Actual `nex_eos_test`, `nex_wc_test`, and `nex_oa_test` PostgreSQL protected
  smoke, including v2 Project-code resolution: PASS.
- Contract validation: PASS (`279` schemas, `322` positive examples, `260`
  negative examples, `10` OpenAPI documents).
- NeX-EOS Slice Gate: PASS (`2,319` passed, `67` skipped; statement
  `96.78%`, branch `94.77%`).
- NeX-AE Slice Gate: PASS (`7,042` passed, `53` skipped; statement `96.47%`,
  branch `94.73%`). The result is above the preceding `96.46%` / `94.72%`
  baseline.
- AE coverage ownership audit: PASS (`200` modules, `113` active-graph
  modules, product statement/branch `97.07%` / `95.02%`, zero conflicts).
- No remote model provider is required by this Slice.

## Next Boundary

`W80-CA00F.5` may now run the Journal and accounting-allocation journeys as two
independently authorized executions. It must prove installed RuntimeJob
scheduling, normal AgentResult/WorkspaceResult publication, restart/replay,
Playwright visibility, and zero-residue behavior on exact head.
