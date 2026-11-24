# W80-CA00F.5A: Accounting Allocation Product Entry and Domain Intent Activation Closure

## 1. Status

- Version: 1.0
- State: CLOSED
- Parent: W80-CA00F
- Resumes: W80-CA00F.5 after this corrective Slice closes

## 2. Problem

W80-CA00F.4 and .4A separated Journal posting from accounting allocation and
introduced the typed `ae.accounting_allocation_work_intent.v1` authority
boundary. The installed allocation Skill, deterministic plan materializer, and
common RuntimeJob activation path exist, but the product entry still lacks a
canonical semantic-admission route. A test or live harness can construct the
typed intent directly, while an ordinary admitted natural-language request
cannot yet reach the same runtime without a scenario-specific bypass.

## 3. Decision

1. `FINANCE.COST_ALLOCATION.RUN` is admitted through the existing semantic
   candidate pipeline and `DomainIntentActivatorRegistry`.
2. The untrusted candidate contract contains only explicit business selectors:
   `company_id`, `journal_id`, `source_record_line_ref`, `source_kind`, and
   contiguous `allocation_project_code_N` / `allocation_ratio_N` pairs.
3. Tenant, principal, execution, WorkIntent, timestamp, source, and publication
   lineage come from trusted runtime context. A provider must not invent them.
4. The activator validates candidate shape and builds the existing typed,
   hash-bound allocation WorkIntent. The typed projection is preserved inside
   the common WorkIntent SoR; no parallel intent table is introduced.
5. A capability-keyed, deterministic Product Coordinator persists an immutable
   READY checkpoint and invokes the existing AgentPlan, Validation,
   ExecutablePlan, scheduler, and RuntimeJob path.
6. Fresh OA `finance:allocation:execute` authority and EOS Project, source,
   approved-plan, allocation, and P&L authority remain execution-time checks.
   Semantic admission does not cache or replace those authorities.
7. Exact replay must return the same candidate binding, checkpoint, plan, and
   RuntimeJob identity. Semantic drift fails closed with zero mutation.

## 4. Candidate Contract

The provider may emit the following scalar parameter candidates for
`FINANCE.COST_ALLOCATION.RUN`:

- `company_id`: explicit canonical company UUID;
- `journal_id`: explicit posted Journal UUID;
- `source_record_line_ref`: explicit EOS source line reference;
- `source_kind`: one supported accounting source kind;
- `allocation_project_code_1..N` and `allocation_ratio_1..N`.

Indexes must be contiguous, Project codes unique, every ratio positive, and the
ratio total exactly `1.000000`. Missing identifiers, malformed UUIDs, unknown
source kinds, incomplete pairs, duplicate Projects, or an invalid total require
clarification or deterministic rejection. The product path must not supply a
default company, Journal, source, ratio, Project count, Plan ID, tenant, or
publication target from deployment configuration or fixture data.

## 5. Product Composition

The allocation activator and coordinator are selected only by immutable
capability identity and admitted capability version. The installed composition
must contain:

1. one allocation DomainIntentActivator registration;
2. one deterministic allocation Product Coordinator registration;
3. one exact installed allocation Skill bundle lock;
4. one immediate READY checkpoint implementation;
5. one existing allocation plan materializer and common RuntimeJob activation;
6. one canonical activation/rollback admission lock.

The existing Journal Product Coordinator and its sequential approval lifecycle
remain unchanged. Allocation does not reuse `READY_FOR_D04`, M1 preparation
checkpoints, business approval receipts, or accounting approval receipts.

## 6. Authority and Publication

- OA authority is evaluated fresh by the installed allocation runtime.
- EOS resolves current ACTIVE Project and company bindings and the exact
  APPROVED AllocationPlan before write execution.
- Allocation and P&L results use the existing IA/accounting publication
  contract and carry their own replay identity and evidence references.
- Journal completion cannot imply allocation completion.

## 7. Prohibited Implementations

- tenant or Project dictionaries;
- fixed ratios or fixed Project counts;
- default AllocationPlan IDs;
- M1, demo, or fixture branches in product code;
- direct test-only invocation as production admission;
- cached OA allow decisions as write authority;
- a new allocation intent or result persistence table.

## 8. Verification

1. candidate parser and activator unit tests for success, clarification, malformed
   pairs, duplicate Projects, invalid totals, and replay drift;
2. registry tests proving exact capability and version selection;
3. coordinator tests proving READY checkpoint persistence and immediate common
   RuntimeJob activation;
4. actual AE PostgreSQL migration/state/restart/replay smoke;
5. OA/EOS deny and stale-authority tests at execution time;
6. residue scans for tenant, ratio, Project-count, fixture, demo, and M1 business
   values;
7. AE Slice Gate with statement and branch coverage at or above baseline;
8. after closure, resume W80-CA00F.5 Journal and allocation live journeys and
   the Repository Full Gate.

## 9. Migration Decision

No database migration is planned. Existing WorkIntent JSON, Product Preparation
checkpoint, AgentPlan, Validation, ExecutablePlan, RuntimeJob, allocation, P&L,
and result-publication persistence is reused.

## 10. As-Built Closure

- Intent prompt `v14` is the sole active intent-resolution binding; `v13` is
  retained as replay-only historical evidence.
- The installed registry admits a generic allocation DomainIntentActivator and
  deterministic Product Coordinator without tenant, Project-count, ratio, Plan
  ID, fixture, or demo defaults.
- A valid candidate becomes the existing typed
  `ae.accounting_allocation_work_intent.v1`, an immutable READY preparation
  checkpoint, deterministic AgentPlan/Validation/ExecutablePlan, and one common
  RuntimeJob. Fresh OA/EOS checks remain in the execution runtime.
- The actual `nex_ae_test` PostgreSQL smoke migrated an isolated schema to the
  repository head, persisted the checkpoint/plan/job lineage, restarted the
  engine, converged exact replay without duplicates, and removed the schema with
  zero residue.
- The AE Slice Gate passed with `7,075 passed`, `55` protected skips, statement
  coverage `96.46%`, branch coverage `94.68%`, and all `6/6` gate commands.
- Remote-provider acceptance was not run in this corrective Slice. W80-CA00F.5
  remains responsible for the two explicit live journeys and Repository Full
  Gate after operator confirmation of DGX availability.
