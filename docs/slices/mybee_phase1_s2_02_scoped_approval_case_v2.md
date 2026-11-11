# MyBee Phase 1 S2-02 ScopedApprovalCase v2

## Status

- Slice: `S2-02`
- Status: implemented and verified
- Requirements: `SRS-MST-003`, `SRS-SEC-001`
- Canonical operation: `FINANCE.ACCOUNTING_APPROVAL.REQUEST`

## Boundary

S2-02 creates a durable Human approval request for one company and an optional
Project scope. It does not approve, reject, or advance the request. WC Human
decision admission and accounting authorization proof remain owned by S2-03.

The existing v1 `eos_approval_instance` contract remains unchanged, including
its non-null `project_id`. Company and multi-Project approval requests use the
new v2 persistence boundary instead of a synthetic Project.

## Persistence

- `eos_scoped_approval_case` owns the immutable request semantics and mutable
  workflow cursor (`state`, active stage, version and decision timestamps).
- `eos_scoped_approval_subject_binding` records exact Project membership in the
  request scope. A `COMPANY` case has zero binding rows.
- An active subject revision is unique for tenant, company, purpose, subject
  reference and revision while state is `PENDING` or `APPROVED`.
- Project bindings are immutable. Material case fields are immutable; future
  S2-03 workflow transitions must advance the optimistic version.
- Every Project is checked as active and approved for the same LegalEntity at
  request time.

Migration: `2527_eos_scoped_approval_case_v2.sql`.

## Trust And Publication

- The caller must present `service:call` trust for audience `nex-eos` on a
  `WRITE` route.
- EOS obtains fresh OA effective authorization and requires
  `finance:journal:request-approval`.
- Optional OA company and Project projections are enforced when present. EOS
  independently checks authoritative LegalEntity and Project bindings.
- Creation is coordinated by the existing EOS BusinessOperation transaction.
- After commit, EOS creates or replays one deterministic WC
  `BUSINESS_FORMAL` ApprovalWorkItem for the active policy stage.
- WC failure never fabricates approval. The committed case remains retryable
  through the same idempotency identity.

## Consumer Contract

`domains/mybee/mybee_ax/integrations/nex_approval_client.py` builds the exact
canonical payload/hash and admits the EOS receipt without importing EOS
repositories or tables.

## Verification

- Focused unit/regression: `25 passed`, protected PostgreSQL case separated.
- Focused new-boundary coverage: `99%` statement/branch aggregate.
- Actual `nex_eos_test` protected smoke: passed.
  - all EOS migrations applied in an isolated schema;
  - `PROJECT_SET` case and two subject bindings committed;
  - `eos_approval_instance.project_id` remained `NOT NULL`;
  - material update and delete were rejected by PostgreSQL triggers;
  - versioned workflow update was admitted;
  - isolated schema was dropped after the test.
- OpenAPI 3.1 validation: passed.
- NeX-EOS Slice Gate: `1112 passed`, `37 skipped`; statement coverage
  `97.08%`, branch coverage `96.27%`.
  - MyBee consumer: statement/branch `100%`.
  - EOS scoped approval service: statement `99.72%`, branch `98.94%`.
  - EOS scoped approval API: statement/branch `100%`.
- Contract validation: `233` schemas, `292` examples, `245` negative
  examples, and `10` OpenAPI documents passed.
- Machine-readable coverage evidence:
  `reports/quality/mybee-s2-02-nex-eos.coverage.json`.

## Deferred To S2-03

- OA Human approver resolution and separation-of-duty checks
- WC decision event admission and idempotent stage advancement
- final `ApprovalProof` production
- terminal approval/rejection projection and accounting acceptance
