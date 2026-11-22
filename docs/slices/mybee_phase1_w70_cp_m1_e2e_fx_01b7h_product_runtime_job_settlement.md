# CP-M1-E2E-FX-01B.7H: Product RuntimeJob Settlement and Lease Fencing Closure

## Status

- Date: `2026-11-20`
- Status: `IMPLEMENTED`; source, regression, and actual PostgreSQL boundary passed;
  protected installed journey pending
- Parent boundary: `CP-M1-E2E-FX-01B.7`
- Database migration: none
- Public API or RuntimeJob schema change: none
- Remote provider: required only for the final installed journey

## Failure Reconciliation

The `.7G` protected journey proved that the installed Product worker received
its admitted 600-second lease and that every observed provider request returned
HTTP 200. The Product `RESUME_EXECUTION` job nevertheless remained `RUNNING`
until its lease expired and was claimed again.

Source reconciliation found that
`InstalledProductCoordinatorAssignmentHandler` resumed the durable approval
checkpoint and activated the resulting plan, but did not settle the claimed
RuntimeJob. The generic worker lifecycle intentionally leaves settlement to the
assignment authority, while the existing executable-step handler already owns
its success and failure settlement. The Product assignment was the missing
authority implementation.

## Decision

- Preserve the existing AgentPlan, ExecutablePlan, ExecutableStep, scheduler,
  and result-finalization contracts.
- Preserve the existing rule that all executable steps must terminalize before
  the AgentExecution moves to `RESULT_VERIFY`.
- Do not add synthetic `BEGIN` or `END` steps in this corrective Slice.
- Make the installed Product assignment handler settle its own RuntimeJob with
  the exact worker and lease token from the claim.
- Complete successful Product resume and activation as `DONE`.
- Record non-retryable failures as `FAILED`.
- Requeue retryable Product failures with the existing RuntimeJob policy using
  a five-second delay and at most three attempts; the third failure becomes
  `DEAD_LETTER` through the existing queue authority.
- Preserve stale-lease fencing. A Product mutation that finishes after its
  lease is no longer current cannot record completion under the old token.

## Implementation

- Added a narrow `ProductRuntimeJobSettlement` dependency to the installed
  Product assignment handler.
- The installed Product planning composition now shares one
  `SqlAlchemyRuntimeJobQueue` between event admission and assignment settlement.
- Success settlement occurs only after checkpoint resume, optional plan
  activation, and terminal execution handling have returned.
- Failure settlement preserves the original exception while recording its
  error code and retry disposition through the existing RuntimeJob API.
- Successful handler evidence now reports the settled RuntimeJob state and
  attempt number without exposing content or secrets.
- No compiler, plan schema, step state, result verification, migration, public
  route, or queue schema was changed.

## Verification

- Ruff and diff checks: `PASS`
- focused Product assignment and protected-smoke regression: `43 passed`, `1`
  protected skip
- focused worker, dispatcher, generalized resume, preparation, activation,
  restart, and installed composition regression: `209 passed`, `1` protected
  skip
- actual `nex_ae_test` PostgreSQL protected smoke: `PASS`
  - current migration head applied in an isolated schema;
  - business approval Product resume job: `RUNNING -> DONE`;
  - accounting approval Product resume job: `RUNNING -> DONE`;
  - both attempt outcomes: `DONE`;
  - deterministic AgentPlan/ExecutablePlan activation completed;
  - existing scheduler produced the first executable-step job as `QUEUED`;
  - isolated schema removed after the run.
- AE Slice Gate: `PASS`
  - tests: `6865 passed`, `53 skipped`;
  - statement coverage: `96.46%`;
  - branch coverage: `94.72%`;
  - product statement coverage: `97.08%`;
  - product branch coverage: `95.01%`;
  - commands: `6/6`.

## Protected Live Rule

The final exact-head installed journey must prove:

1. each Product `RESUME_EXECUTION` attempt reaches `DONE` before lease expiry;
2. no second Product attempt is created after successful settlement;
3. the existing executable-step scheduler advances the plan without a new
   lifecycle marker;
4. all executable steps terminalize and the execution reaches `RESULT_VERIFY`;
5. AgentResult and IA workspace publication reach terminal success exactly once;
6. all isolated database schemas and Compose resources are removed.

Until this live run passes, `.7H` closes the source, regression, and PostgreSQL
settlement boundary but does not close the parent `.7` journey.
