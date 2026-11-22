# MyBee Phase 1 S1-06 Project WorkAssignment and Payroll Privacy

## Scope

S1-06 closes `SRS-PRJ-005` and `SRS-PRJ-006` for the Phase-1 planning
boundary. It adds immutable Project WorkAssignment planning after the S1-05
WorkCodeSet admission without turning Project membership into universal
execution authority and without exposing employee payroll data.

## Persistence Boundary

- `eos_project_work_assignment` is the only new table.
- Every assignment pins the tenant, Project, exact WorkCodeSet revision,
  canonical FL work code, performer, scope, Grade policy, approved proof, and
  effective period.
- Planned Man-Day is an exact positive `NUMERIC(12,4)` value. Binary float is
  not admitted by the application contract.
- A human performer requires both fresh OA
  `project:work-assignment:perform` authority and an active non-viewer Project
  membership effective at assignment start.
- An Agent performer must be the PA identity already admitted by the selected
  WorkCodeSet revision.
- PostgreSQL serializes competing overlap checks with a transaction advisory
  lock. An overlapping assignment for the same Project, performer, and work
  code is rejected.
- Assignment history is append-only. Direct update and delete fail closed.

## Privacy Boundary

The standard PA/PM projection contains Grade and planned Man-Day only. It does
not contain salary, payroll amount, actual day rate, actual payroll cost, or
compensation. These fields are rejected at command admission and cannot be
persisted by the S1-06 table or returned by the OpenAPI schema.

Actual payroll and actual labor cost remain a future protected cost-source
boundary. They must not be inferred from Grade or planned Man-Day and must not
be added to this read model.

## API and Trust

- `POST /internal/v2/projects/{project_id}/work-assignments:assign`
  - operation `PROJECT.WORK_ASSIGNMENT.ASSIGN`;
  - signed `service:call`, fresh OA manage authority, owner/manager Project
    membership, and valid performer authority are required;
  - EOS BusinessOperation idempotency provides exact replay.
- `GET /internal/v2/projects/{project_id}/work-assignments`
  - operation `PROJECT.WORK_ASSIGNMENT.LIST`;
  - signed trust, fresh OA read authority, and Project membership are required
    unless current Project administrator authority is present;
  - the response explicitly marks `INTERNAL_PLANNING` and
    `private_payroll_excluded=true`.

The MyBee consumer is transport-neutral and produces the same canonical NSL
payload hash as EOS. NSL Skill/Tool binding remains outside S1-06.

## Compatibility

- Migration `2525_eos_project_work_assignment` is additive; prior migration
  history was not rewritten.
- The shared operation registry version is `mybee-s1-06.v1`.
- The EOS OpenAPI digest and MyBee exact platform lock were advanced together.
- S1-05 BusinessReady inputs and state rules are unchanged. WorkAssignment is
  a downstream planning record, not another BusinessReady prerequisite.

## Verification

- Focused WorkAssignment and MyBee adapter suite: `49 passed`, with the
  protected PostgreSQL case explicitly disabled in the fast run.
- Focused new-module coverage: statement/branch combined `99%`.
  - MyBee workforce planning adapter: statement and branch `100%`.
  - EOS WorkAssignment API: statement and branch `100%`.
  - EOS WorkAssignment domain/persistence service: statement `99.43%`, branch
    `100%`.
- MyBee, S1-05, operation-registry, lock, and architecture regression:
  `157 passed`, `2` protected tests explicitly skipped.
- Actual `nex_eos_test` protected PostgreSQL smoke passed: migration `2525`
  applied in an isolated schema, two concurrent overlapping writes produced
  exactly one success and one conflict, update/delete were rejected, and
  cleanup left zero test schemas.
- Contract validation passed for `233` schemas, `292` examples, `245`
  negative examples, and `10` OpenAPI documents.
- EOS/MyBee Slice Gate passed all `6/6` commands with `1077 passed` and `35`
  explicitly protected tests skipped. Service coverage was statement `96.89%`
  and branch `95.99%` against the `95%`/`94%` thresholds.
- Golden Journey transition and demo/product dependency audits passed with no
  findings.
- Remote model providers are outside this deterministic EOS boundary and were
  not required.
