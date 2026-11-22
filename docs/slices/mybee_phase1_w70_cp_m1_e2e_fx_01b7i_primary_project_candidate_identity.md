# CP-M1-E2E-FX-01B.7I: Primary Project Candidate Identity and Deterministic Delegation Admission

## Status

- Date: `2026-11-20`
- Status: `CORRECTIVE OBJECTIVE VERIFIED`; source, PostgreSQL, AE Slice Gate,
  and protected primary-identity handoff passed; parent journey remains blocked
  at the downstream Product approval-resume boundary
- Parent boundary: `CP-M1-E2E-FX-01B.7`
- Database migration: none
- Public API or persisted schema change: none
- Remote provider: required only for the final protected installed journey

## Failure Reconciliation

The exact-head protected journey reached the WC-to-AE Project Agent handoff but
the handoff dead-lettered with `PROJECT_CODE_AMBIGUOUS`. The admitted user
request named one primary Project and two allocation targets. The provider
returned both Project Codes as entity selectors, while the Product activator
required exactly one Project-shaped selector and had no typed role identity
with which to distinguish the primary Project.

Selecting the first selector, the highest-confidence selector, or a fixed
allocation position would make delegation dependent on provider ordering and
would repeat the scenario-specific behavior retired earlier in W70.

## Decision

- The active intent prompt is promoted from `v11` to `v12`.
- `FINANCE.VOUCHER.APPROVE_AND_POST` candidates must emit exactly one scalar
  `primary_project_code` parameter.
- The value must be a valid Project Code, must occur in the requested
  allocation set, and must match exactly one Project entity selector.
- Every other Project-shaped selector must be unique and must also identify an
  allocation target. Unknown or duplicate Project selectors fail closed.
- Admission retains only the matched primary Project selector in the canonical
  WorkIntent. Allocation targets remain typed parameters and business context.
- Selector order and confidence never choose the delegated Project.
- The Product activator independently revalidates the typed primary identity
  against allocation parameters and raw selectors before contacting EOS or OA.
- Historical `v11` prompt content remains replay-only. A legacy candidate
  without `primary_project_code` is accepted only when it contains exactly one
  explicit Project Code, preserving existing replay semantics.

## Implementation

- Added the required primary Project candidate to business-context admission
  and canonical WorkIntent parameter projection.
- Replaced single-selector admission with deterministic typed identity,
  allocation membership, uniqueness, and unknown-selector checks.
- Added a defense-in-depth check to the Project delegation activator while
  retaining its exact single-selector legacy path.
- Added prompt Registry `v12` and preserved `v11` as replay-only history.
- No Project authority is inferred. EOS still resolves the Project, OA still
  authorizes the requester, and the synchronized AE Project Agent must still be
  active before delegation.

## Verification

- formatter, Ruff, and diff checks: `PASS`
- focused candidate, business-context, delegation, and prompt persistence
  regression: `186 passed`
- expanded M1 Product regression: `305 passed`, `3` protected PostgreSQL skips
- actual `nex_ae_test` PostgreSQL smoke: `PASS`
  - all migrations current;
  - prompt persistence, binding history, WorkIntent replay, and cleanup passed;
  - active intent binding is `v12` and historical `v11` remains present;
  - no remote provider was contacted.
- AE Slice Gate: `PASS`
  - tests: `6870 passed`, `53 skipped`;
  - statement coverage: `96.46%`;
  - branch coverage: `94.72%`;
  - product statement coverage: `97.08%`;
  - product branch coverage: `95.01%`;
  - commands: `6/6`.
- Golden A quarantine Gate: `PASS`; its active-prompt assertion now admits the
  exact scenario-free `v12` primary-identity contract.
- A pre-existing legacy v7 metadata mismatch was observed only when replaying
  every historical prompt row in the long-lived test database. It was not
  rewritten in this Slice; current v12 activation used the existing atomic
  binding API and passed.
- exact-head canonical OCI evidence: `PASS`
  - source revision: `d1514b394ba0173016b5ffcb2ce77c2fc1726f32`;
  - nine images, nine immutable manifests, nine non-root images;
  - twelve background/package checks passed;
  - the dedicated AE Product Runtime image was rebuilt from the same admitted
    AE base image and NSL v0.2.1 wheel.
- exact-head DGX-backed installed journey: `PRIMARY IDENTITY PASS`, downstream
  Product resume `BLOCKED`
  - Qwen3.5-9B on canonical port `9111` returned HTTP 200 for both observed
    generation calls;
  - the v12 WorkIntent retained one typed primary Project and both allocation
    targets, while canonical admission retained one delegation selector;
  - WC routed and claimed one PA assignment without
    `PROJECT_CODE_AMBIGUOUS`;
  - one `BUSINESS_FORMAL` approval was created, approved, and delivered;
  - the generalized AE approval event was `MATCHED` and its Product wait was
    `RESUME_QUEUED`;
  - the downstream `RESUME_EXECUTION` attempt then terminated non-retryably as
    `ae.product_coordinator_assignment_failed`, leaving the PA execution at
    `WAITING_APPROVAL:PLAN_BUILD` and the browser at result timeout;
  - bounded diagnostics observed EOS/WC terminal binding differences for
    policy version and target role, but the current generic error reference is
    insufficient to prove that those differences caused the exception;
  - all eight isolated PostgreSQL schemas were removed and Compose resources
    were stopped; zero-residue passed.

## Resume Decision

The `.7I` defect is closed: primary Project identity is typed, deterministic,
provider-order independent, and proved in the installed path. The parent
`CP-M1-E2E-FX-01B.7` journey is not closed because the next authority-backed
Product resume failed after approval delivery.

Do not widen `.7I` or change approval contracts from the bounded diagnostic
alone. The next corrective boundary should first preserve a typed, redacted
Product coordinator failure code and reconcile the exact ApprovedDocument
receipt/reference plus EOS/WC terminal policy-version and target-role semantics.
Only then may the same protected journey be replayed.

## Protected Live Rule

The next protected journey must prove that a request containing one primary
Project and multiple allocation Projects:

1. persists prompt `v12` provenance and one typed `primary_project_code`;
2. admits the primary Project independently of selector order or confidence;
3. delegates to the EOS/OA-authorized active Project Agent exactly once;
4. preserves every allocation target for downstream preparation;
5. does not create a `PROJECT_CODE_AMBIGUOUS` or duplicate handoff outcome;
6. preserves the `.7H` RuntimeJob settlement and zero-residue guarantees.
