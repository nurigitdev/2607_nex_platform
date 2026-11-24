# W80-CA00F.5A: Accounting Allocation Product Entry and Domain Intent Activation Closure

## Outcome

- Added the generic `FINANCE.COST_ALLOCATION.RUN` semantic-admission path. The
  candidate carries only explicit company, Journal, source-line, source-kind,
  and contiguous Project/ratio values; trusted runtime context supplies tenant,
  principal, execution, source, and publication lineage.
- Registered the allocation DomainIntentActivator beside existing Product
  activators and converted accepted candidates into the existing typed,
  hash-bound `ae.accounting_allocation_work_intent.v1` contract.
- Added a deterministic allocation Product Coordinator that persists an
  immediate READY checkpoint and invokes the existing common plan persistence,
  scheduling, and RuntimeJob activation path. It introduces no approval wait,
  scenario branch, or parallel persistence model.
- Added immutable allocation coordinator activation/rollback locks and promoted
  the installed MyBee capability/runtime/coordinator release set. Compose and
  OCI packaging now carry the same canonical files.
- Corrected prompt lifecycle admission: `v14` is active and `v13` is replay-only
  history. This closed a discovered bootstrap defect where the older same-key
  prompt could otherwise be selected again.

## Product Boundaries

- Fresh OA `finance:allocation:execute` and EOS Project/source/approved-plan
  authority remain execution-time checks.
- Journal completion still cannot imply allocation or Project P&L completion.
- No tenant dictionary, default ratio, fixed Project count, fixture Plan ID,
  M1 scenario value, or demo branch was added.
- Existing WorkIntent, Product Preparation, AgentPlan, Validation,
  ExecutablePlan, RuntimeJob, allocation, P&L, and publication storage is reused;
  there is no database migration.

## Verification

- New focused unit and branch suite: `24 passed`, `1` protected skip.
- New-module focused coverage: statement/branch combined `97%`;
  `accounting_allocation_intent_activation.py` `98%` and
  `accounting_allocation_product_coordinator.py` `96%`.
- Prompt, lock, ownership, and prior Product runtime regression: `164 passed`,
  `1` protected skip.
- Actual AE PostgreSQL smoke against `nex_ae_test`: `25 passed`. The smoke used
  an isolated schema, migrated to the current head, persisted exactly one
  preparation checkpoint, AgentPlan, Validation, ExecutablePlan, ExecutableStep,
  and RuntimeJob, restarted the engine, converged exact replay, and dropped the
  schema with zero residue.
- Canonical AE Slice Gate: PASS, `7,075 passed`, `55 skipped`, `6/6` commands;
  statement coverage `96.46%`, branch coverage `94.68%`.
- Contract validation: PASS, `279` schemas, `322` examples, `260` negative
  examples, and `10` OpenAPI documents.
- Golden-journey transition, demo dependency, and AE ownership audits: PASS;
  active import graph `117`, ownership conflicts `0`.

## Next Boundary

Resume `W80-CA00F.5` with two separate installed live journeys: Journal posting
through IA result publication, and accounting-authorized allocation through
Project P&L refresh. DGX-backed generation and the Repository Full Gate are not
part of this corrective Slice and require an explicit operator go-ahead.
