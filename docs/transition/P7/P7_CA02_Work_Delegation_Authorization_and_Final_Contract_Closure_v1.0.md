# P7-CA02 — Work Delegation Authorization & Final Contract Closure v1.0

**Status:** CLOSED / P7 FINAL FREEZE RESTORED
**Phase:** P7 Final Closure Amendment
**Purpose:** Close the missing Work Delegation authorization boundary before P7 Final Freeze
**Predecessor:** P7-S9 Golden B + Repository Full Gate — PASS
**Current P7 State:** P7-CA02 CLOSED / FULL GATE PASS / P8 ENTRY AUTHORIZED
**Target Exit:** P7 FROZEN / P8 ENTRY AUTHORIZED
**Reviewed Baseline HEAD:** `1918d9bc2c8f65818079cd3102a500b08623faba`
**Date:** 2026-10-19

---

## 1. Amendment Objective

P7 implementation and Full Gate are complete, but final repository review found one authority-chain gap and several closure hygiene items that must be corrected before P7 is declared Frozen.

The critical gap is:

```text
P7-CA01 intended authority chain:

DELEGATE_WORK
→ fresh OA work:delegate authorization
→ WC WorkItem
→ fresh OA work:claim authorization
→ Claim / Assignment
→ CLAIMED_WORKITEM AgentExecution
→ execution
→ fresh OA work:result:submit authorization
→ WorkResult
```

Current As-Built behavior is:

```text
DELEGATE_WORK
→ service-token validation only
→ WC WorkItem
→ OA work:claim authorization
→ Claim / Assignment
→ CLAIMED_WORKITEM AgentExecution
→ execution
→ OA work:result:submit authorization
→ WorkResult
```

Therefore a requester lacking `work:delegate` but still possessing `work:claim` may currently create delegated work and reach background execution.

This amendment SHALL close that gap without redesigning P7.

---

## 2. Authority and Scope

P7-CA02 is subordinate to:

```text
Integrated Frozen v2.1 Final Freeze
> Frozen Agent v2.1 / NSL v0.2
> Frozen WC contracts
> P6 / P6.5 As-Built baselines
> P7-CA01 source-backed closure
> P7 As-Built implementation
> this P7-CA02 amendment
> implementation convenience
```

P7-CA02 SHALL NOT modify Frozen source material.

P7-CA02 SHALL NOT introduce:

```text
NSL WRITE
Approval
Enterprise OS transaction
CommitState / VerificationStatus
UNKNOWN_COMMIT_STATE
Schedule / recurring work
Human executor
External A2A Agent
Kafka requirement
```

The amendment is strictly limited to:

```text
1. WorkItem create-time work:delegate authorization
2. OA subject-denial versus dependency-failure classification
3. authorization evidence
4. requester-safe idempotent replay
5. negative authorization tests
6. Golden B authorization coverage
7. WC OpenAPI parity
8. final P7 rerun / documentation closure
```

---

## 3. Final Authority Chain

After P7-CA02, the mandatory authority chain SHALL be:

```text
LLM PlanCandidate
        │
        ▼
Deterministic Plan Admission
        │
        ▼
PlanValidation = VALID
        │
        ▼
Deterministic Compiler
        │
        ▼
DELEGATE_WORK ExecutableStep
        │
        ▼
Fresh OA Authorization
scope = work:delegate
        │
        ▼
WC WorkItem
        │
        ▼
Deterministic Routing
        │
        ▼
Fresh OA Authorization
scope = work:claim
        │
        ▼
Atomic Claim + Assignment
        │
        ▼
ClaimExecutionHandoff
        │
        ▼
CLAIMED_WORKITEM AgentExecution
        │
        ▼
P6.5 Planning + P6 Runtime / NSL READ
        │
        ▼
AgentResult
        │
        ▼
Fresh OA Authorization
scope = work:result:submit
        │
        ▼
WC WorkResult
        │
        ▼
WORK_RESULT_SUBMITTED
        │
        ▼
RESUME_EXECUTION
```

Core invariant:

> **No delegated WorkItem may exist unless the current requester is explicitly authorized to delegate work at the moment the WorkItem is created.**

---

## 4. P7-CA02-DEC-01 — WorkItem Create Requires Fresh OA Authorization

`WorkItemService.create()` SHALL NOT rely only on service-to-service token admission.

Before creating or idempotently resolving a delegated WorkItem, the service SHALL:

```text
1. extract requester identity from the request;
2. call current OA effective-authorization;
3. require active == true;
4. require scope work:delegate;
5. capture metadata-safe authorization evidence;
6. only then perform WorkItem insert-or-verify.
```

The authorization check SHALL occur immediately before the WorkItem persistence boundary.

Required rule:

```text
active != true
OR
work:delegate not in scopes
→ FAIL CLOSED
→ WorkItem count remains 0
```

No fallback is permitted.

---

## 5. P7-CA02-DEC-02 — AuthorizationSource Injection

The existing WC `AuthorizationSource` abstraction SHALL be reused.

Preferred composition:

```text
WorkItemService(
    repository,
    authorization_source=AUTHORIZATION_SOURCE,
    ...
)
```

The same source already used by:

```text
WorkCoordinationService
WorkResultService
```

SHALL be reused for WorkItem create authorization.

Do NOT create:

```text
another OA client
another authorization cache
another local permission registry
```

Production composition in `services/nex-wc/nex_wc/main.py` SHALL inject the existing `AUTHORIZATION_SOURCE` instance.

---

## 6. P7-CA02-DEC-03 — Exact Authorization Rule

The requester subject is the authority subject.

Canonical input:

```text
requester.entity_id
```

Required OA response shape:

```text
active
scopes
revision_hash
```

Required condition:

```text
authorization.active is True
AND
authorization.scopes is a sequence
AND
"work:delegate" in authorization.scopes
```

Otherwise:

```text
error_code = wc.work_item_authorization_denied
HTTP = 403
retryable = false
```

OA unavailable:

```text
error_code = wc.work_item_authorization_unavailable
HTTP = 503
retryable = true
```

Malformed OA authorization response SHALL fail closed.

### 6.1 OA Denial and Dependency-Failure Classification

The current `HttpAuthorizationSource` adds `active=True` only after a successful
OA effective-authorization response. OA rejects an inactive membership with an
HTTP problem response, which the current generic HTTP adapter collapses into a
general runtime exception. Without a typed distinction, WC can incorrectly map
an inactive requester to dependency unavailability.

P7-CA02 SHALL introduce the smallest typed distinction necessary to preserve
the OA decision across the existing `AuthorizationSource` boundary.

Required classification:

```text
OA subject decision:
  oa.authorization_membership_inactive
  oa.authorization_membership_not_found
  or an otherwise valid response that is inactive / lacks the required scope
  -> authorization denied
  -> WC 403
  -> retryable = false

OA dependency or trust failure:
  timeout / connection failure
  OA 5xx
  invalid or missing WC-to-OA service credential
  unrecognized upstream authorization failure
  -> authorization unavailable
  -> WC 503
  -> retryable = true

Malformed successful authorization payload:
  missing/invalid active, scopes, or revision_hash semantics
  -> fail closed as authorization denied
  -> WC 403
  -> retryable = false
```

The adapter SHALL inspect only metadata-safe OA problem fields needed for this
classification. It SHALL NOT expose or persist the raw OA response.

The typed subject-denial signal SHALL be understood consistently by the three
existing WC authority gates:

```text
WorkItem create       -> wc.work_item_authorization_denied
Claim commit          -> wc.claim_authorization_denied
WorkResult submit     -> wc.work_result_authorization_denied
```

All other source failures retain the corresponding
`*_authorization_unavailable` behavior. This is semantic hardening of the
existing authority chain, not a new authorization framework.

---

## 7. P7-CA02-DEC-04 — Authorization Evidence

WC SHALL persist metadata-safe create authorization evidence.

Preferred fields on `wc_work_item`:

```text
create_authorization_revision_hash TEXT
create_authorization_checked_at TIMESTAMPTZ
create_authorized_subject_id TEXT
```

Application-level P7-CA02 creation MUST require all three.

Do NOT persist:

```text
raw token
full OA response
role list unless separately required
service credential
session credential
hidden authorization internals
```

Authorization evidence is an audit reference, not a reusable authorization grant.

A previous `work:delegate` authorization decision SHALL NOT substitute for later `work:claim` or `work:result:submit` checks.

---

## 8. Migration Requirement

Add one additive WC migration after current head:

```text
1003_wc_work_item_authorization.sql
```

Expected changes:

```text
ALTER TABLE wc_work_item
ADD create_authorization_revision_hash
ADD create_authorization_checked_at
ADD create_authorized_subject_id
```

Migration SHALL be:

```text
additive
historical-row aware
non-destructive
service-local
```

Do not fabricate valid OA authorization history for old records.

If historical compatibility requires nullable DB columns, application-level creation after CA02 still SHALL require all evidence fields.

---

## 9. WorkItem Idempotency Semantics

Authorization MUST be evaluated on every create request before returning an idempotent existing WorkItem.

Incorrect:

```text
first request authorized
→ WorkItem created

authorization revoked

same semantic create replay
→ existing WorkItem returned without current authorization check
```

Required:

```text
every WorkItem create/replay request
→ current work:delegate authorization check first
→ then insert-or-verify
```

Therefore:

```text
authorization revoked after original create
+ retry same delegation
→ 403
```

The existing WorkItem remains unchanged.

### 9.1 Requester-Safe Idempotent Replay

The existing WorkItem semantic key SHALL remain unchanged. P7-CA02 SHALL NOT
rewrite historical idempotency identities merely to add requester protection.

After the mandatory current authorization check and before an existing
WorkItem is returned, semantic verification SHALL additionally require:

```text
existing.work_item.requester.entity_id
== current request.requester.entity_id
```

A different authorized requester replaying the same delegation identity SHALL
receive:

```text
error_code = wc.work_item_idempotency_conflict
HTTP = 409
retryable = false
```

The existing WorkItem remains unchanged and no routing, Claim, Assignment,
handoff, or child AgentExecution mutation may occur.

Required ordering:

```text
current requester work:delegate authorization
-> repository insert-or-verify
-> existing requester equality verification
-> return created/existing WorkItem
```

This prevents `accountable_owner`, parent Agent, claimant Agent, service
principal, or another authorized requester from being substituted for the
requester that owns the original delegation replay.

---

## 10. Revoke Race Requirement

Required race:

```text
PlanValidation = VALID
→ DELEGATE_WORK compiled
→ requester work:delegate revoked
→ WC WorkItem create attempted
```

Expected:

```text
WorkItem create = DENIED
new WorkItem rows = 0
Claim rows = 0
Assignment rows = 0
Claim handoff rows = 0
Child AgentExecution rows = 0
```

Planning-time or compile-time authorization SHALL NOT act as create-time authority.

---

## 11. Negative Authorization Test Matrix

### P7-CA02-N01 — No work:delegate

```text
active = true
scopes = [work:claim, work:result:submit]
```

Expected:

```text
WorkItem create = 403
WorkItem = 0
Claim = 0
Assignment = 0
AgentExecution = 0
```

### P7-CA02-N02 — Inactive requester

```text
active = false
scopes includes work:delegate
```

Expected: `403`, zero mutation.

### P7-CA02-N03 — OA unavailable

Expected: `503 retryable`, zero mutation.

### P7-CA02-N04 — Malformed scopes

Examples:

```text
scopes = null
scopes = "work:delegate"
scopes = malformed object
```

Expected: fail closed, zero mutation.

### P7-CA02-N05 — Authorization revoked after planning

```text
provider candidate
→ deterministic plan validation
→ compile
→ revoke work:delegate
→ execute DELEGATE_WORK
```

Expected:

```text
WC create denied
parent step does not create WorkItem
no Claim
no child AgentExecution
```

### P7-CA02-N06 — Idempotent replay after revoke

```text
authorized create succeeds
→ revoke work:delegate
→ retry exact same WorkItem create
```

Expected:

```text
403
existing WorkItem unchanged
no new WorkItem
no new Claim
```

### P7-CA02-N07 — Wrong requester authority

The service SHALL NOT substitute:

```text
accountable_owner
parent Agent
claimant Agent
service principal
```

for the canonical requester.

Authorization subject = `requester.entity_id`.

Also verify:

```text
authorized requester A creates WorkItem
authorized requester B replays the same delegation identity
-> 409 wc.work_item_idempotency_conflict
-> existing requester remains A
-> zero additional mutation
```

---

## 12. Positive Authorization Tests

Required:

```text
active = true
scopes includes work:delegate
```

Expected:

```text
WorkItem create succeeds
authorization evidence stored
restart read preserves evidence
idempotent replay succeeds only while current authorization still allows it
```

Also prove:

```text
work:delegate alone
does NOT imply
work:claim
or
work:result:submit
```

The three authority gates remain distinct.

---

## 13. Golden B Amendment

Current Golden B fixture SHALL explicitly grant:

```python
scopes = [
    "work:delegate",
    "work:claim",
    "work:result:submit",
]
```

Golden B SHALL confirm the three separate authorization boundaries:

```text
WorkItem create authorization calls >= 1
Claim authorization calls >= 1
WorkResult authorization calls >= 1
```

Preferred evidence projection:

```text
OA membership bootstrap calls
OA effective authorization reads
work:delegate gate observed
work:claim gate observed
work:result:submit gate observed
```

Do not expose token or raw OA response.

---

## 14. Golden B Negative Variant

Add a protected negative variant using actual:

```text
nex_oa_test
nex_wc_test
nex_ae_test
```

with requester scopes:

```text
work:claim
work:result:submit
```

and intentionally without:

```text
work:delegate
```

Run the actual DELEGATE_WORK boundary.

Required:

```text
authorization denied at WorkItem creation
wc_work_item new rows = 0
wc_assignment new rows = 0
wc_claim new rows = 0
CLAIM_EXECUTION_HANDOFF outbox new rows = 0
child ae_agent_execution new rows = 0
child runtime jobs new rows = 0
owned residue after cleanup = 0
```

Suggested evidence:

```text
reports/live/p7-ca02-work-delegate-denied-postgres.json
```

No live generation call is required for this isolated negative smoke if a source-backed compiled P7 `DELEGATE_WORK` fixture is used.

The final positive Golden B MUST still use the live generation provider.

---

## 15. WC OpenAPI Update

Update:

```text
contracts/openapi/nex-wc.openapi.yaml
```

At minimum:

1. bump version from the S1-era version;
2. document WorkItem create authorization behavior;
3. document `403 work:delegate denied`;
4. add the existing runtime WorkResult route:

```text
POST /api/v1/work-items/{work_item_id}/results
```

5. document caller restriction to `nex-ae-api`;
6. document expected version and WorkResult request shape;
7. document responses:

```text
201 created
200 idempotent replay
401 invalid service token
403 authorization denied / caller denied
409 stale Claim / Assignment / version / semantic conflict
503 OA/WC unavailable
```

OpenAPI SHALL reflect current P7 As-Built runtime.

---

## 16. Runtime / OpenAPI Parity Test

Add or strengthen automated parity coverage.

Expected path set includes:

```text
/api/v1/work-items
/api/v1/work-items/{work_item_id}
/api/v1/work-items/{work_item_id}/status
/api/v1/work-items/{work_item_id}/route
/api/v1/work-items/{work_item_id}/claim
/api/v1/work-items/{work_item_id}/results
```

Reuse existing platform contract-validation utilities where possible.

Do not create a second contract-validation framework.

---

## 17. AG Operations Projection Traceability

P7 SRS contains a metadata-safe WC operations projection requirement.

P7-CA02 SHALL resolve its closure status explicitly.

Choose one:

```text
A. IMPLEMENTED
   → cite exact WC/AG projection API and tests

OR

B. DEFERRED (SELECTED)
   → amend P7 Final As-Built / SRS traceability
   → state that detailed WC operational projection is deferred
   → keep health/ready/log/job-control baseline explicit
```

Do not leave the requirement appearing fully closed if no specific implementation exists.

This is documentation/traceability closure and is not a blocker to the delegation authorization code itself.

Selected disposition: `B. DEFERRED`. No dedicated WC counts/routing/lease/
outbox/result projection API exists in the current AG source. The Final
As-Built records this explicitly while retaining the platform health,
readiness, logging, and job-control baselines.

---

## 18. Evidence Revision Hygiene

For final protected evidence, record:

```text
source_revision_under_test
tested_tree_digest (recommended)
migration heads
provider profile/model
prompt binding versions
NSL revision
authorization gate counts
quality gate metrics
cleanup counts
```

If test → evidence → commit ordering prevents the final commit SHA from being known at run time, explicitly distinguish:

```text
source_revision_under_test
final_closure_commit
```

---

## 19. Expected Source Changes

Likely modified:

```text
services/nex-wc/nex_wc/work_items.py
services/nex-wc/nex_wc/main.py
services/nex-wc/nex_wc/work_item_api.py
services/nex-wc/nex_wc/coordination_clients.py
services/nex-wc/nex_wc/coordination.py
services/nex-wc/nex_wc/work_results.py
contracts/openapi/nex-wc.openapi.yaml
scripts/smoke/run_p7_s9_postgres_live_golden_b.py
tests/test_nex_wc_p7_s1_work_items.py
tests/test_nex_wc_p7_s1_postgres.py
tests/test_ae_wc_oa_p7_s9_postgres_live_golden_b.py
```

Likely new:

```text
database/nex-wc/migrations/1003_wc_work_item_authorization.sql
tests/test_nex_wc_p7_ca02_work_delegate_authorization.py
tests/test_ae_wc_oa_p7_ca02_postgres_authorization.py
scripts/smoke/run_p7_ca02_work_delegate_denied_postgres.py
reports/live/p7-ca02-work-delegate-denied-postgres.json
docs/slices/p7_ca02_work_delegation_authorization_final_contract_closure.md
```

Exact naming may follow existing repository conventions.

---

## 20. Refactoring-First Rule

Before changing WorkItem creation:

```text
1. inspect WorkItemService
2. inspect AuthorizationSource
3. inspect HttpAuthorizationSource
4. inspect OA effective authorization contract
5. preserve typed OA subject denial separately from transport/configuration failure
6. reuse existing typed error conventions
7. avoid duplicating authorization parsing
```

If useful, extract a small shared helper for:

```text
active authorization + required scope + revision hash
```

but only if it reduces duplication across:

```text
WorkItem create
Claim
WorkResult submit
```

Do not perform a broad authorization framework rewrite.

---

## 21. Required Test Sequence

Recommended:

```text
P7-CA02 focused unit tests

→ WC Slice Gate

→ AE/WC/OA affected regression

→ actual PostgreSQL positive authorization smoke

→ actual PostgreSQL negative work:delegate-denied smoke

→ P7-S8 recovery smoke

→ P7-S9 live Golden B rerun

→ contract validation

→ Repository Full Gate
```

---

## 22. Quality Thresholds

Use existing repository policy.

Minimum:

```text
statement coverage >= 95%
branch coverage    >= 94%
```

No threshold weakening is authorized.

All P4-P7 regressions SHALL remain green.

---

## 23. P7-S9 Golden B Rerun Requirements

Final positive Golden B SHALL prove:

```text
actual PostgreSQL AE/WC/OA
actual live MO generation
INTENT / CONTEXT / PLAN
current prompt versions
current P7 migrations
current WC authorization migration
work:delegate PASS
work:claim PASS
work:result:submit PASS
ClaimGeneration exact
one child AgentExecution
one WC WorkResult
one RESUME_EXECUTION
parent deterministic continuation
restart/idempotency
zero residue
```

Expected updated WC migration head:

```text
1003_wc_work_item_authorization
```

---

## 24. Repository Full Gate

After Golden B, rerun:

```text
Repository Full Gate
```

Expected:

```text
all tests PASS
coverage PASS
contract validation PASS
OpenAPI validation PASS
no unexpected skipped mandatory tests
```

Protected live tests may remain opt-in in ordinary Full Gate, but fresh P7-CA02 protected evidence must exist separately.

---

## 25. Documentation Amendment

After tests pass, amend:

```text
docs/transition/P7/README.md
docs/transition/P7/P7_Final_AsBuilt_Baseline_and_P8_Handoff_v1.0.md
```

Add explicit closure of:

```text
work:delegate create-time authorization
authorization evidence
negative no-delegate test
Golden B rerun
WC OpenAPI parity
final Full Gate
```

Recommended Final As-Built authority chain:

```text
DELEGATE_WORK
→ fresh OA work:delegate
→ WorkItem
→ deterministic routing
→ fresh OA work:claim
→ atomic Claim / Assignment
→ CLAIMED_WORKITEM AgentExecution
→ existing semantic planning/runtime
→ AgentResult
→ fresh OA work:result:submit
→ WorkResult ACK
→ RESUME_EXECUTION
→ parent continuation
```

---

## 26. Final P7 State Transition

Before CA02:

```text
P7 IMPLEMENTATION COMPLETE
P7 FULL GATE PASS
P7 FINAL FREEZE = HOLD
P8 ENTRY = HOLD
```

After all CA02 gates pass:

```text
P7-CA02 = CLOSED

P7 =
FINAL
CLOSED
FROZEN

P8 ENTRY =
AUTHORIZED
```

---

## 27. Required Closure Evidence

P7-CA02 SHALL close only when all are true:

```text
[x] WorkItem create calls current OA effective authorization
[x] active requester required
[x] work:delegate scope required
[x] missing work:delegate fails closed
[x] inactive OA subject maps to 403 rather than 503
[x] OA dependency/trust failure maps to retryable 503
[x] OA unavailable fails closed
[x] malformed authorization fails closed
[x] authorization evidence stored metadata-safely
[x] create idempotent replay rechecks current authorization
[x] different requester replay returns 409 with zero mutation
[x] revoke-after-planning race fails closed
[x] positive authorization PostgreSQL test PASS
[x] negative no-delegate PostgreSQL test PASS
[x] negative path WorkItem new rows = 0
[x] negative path Claim new rows = 0
[x] negative path AgentExecution new rows = 0
[x] Golden B scopes include work:delegate
[x] Golden B live rerun PASS
[x] WC OpenAPI includes WorkResult runtime route
[x] runtime/OpenAPI parity PASS
[x] AG projection requirement status explicitly closed or deferred
[x] evidence revision hygiene updated
[x] Repository Full Gate PASS
[x] zero owned residue
[x] Final As-Built amended
```

---

## 28. Suggested Commit Sequence

```text
fix(wc): require fresh delegation authorization
test(p7): add work-delegate fail-closed acceptance
docs(api): align WC OpenAPI with P7 runtime
test(p7): rerun golden b after delegation authorization
docs(p7): freeze final authority contract
```

Each commit follows:

```text
refactor if needed
→ implementation
→ focused tests
→ regression
→ commit
```

---

## 29. Final Invariants

After P7-CA02:

```text
LLM Candidate != authorization

PlanValidation != authorization

DELEGATE_WORK
requires current work:delegate

WorkItem != execution authority

RoutingDecision != execution authority

Claim = background execution authority

CLAIMED_WORKITEM
requires current Claim lineage

AgentResult != completed business handoff

WorkResult submit
requires current work:result:submit

one satisfied wait
→ at most one RESUME_EXECUTION
```

Most important:

> **Natural-language planning may request delegated work, but only current deterministic OA authority may create that Work.**

---

## 30. Codex Execution Instruction

Implement P7-CA02 as a controlled amendment to the existing P7 source.

Do not redesign P7.

Do not edit Frozen v2.1 documents.

Start by reading:

```text
services/nex-wc/nex_wc/work_items.py
services/nex-wc/nex_wc/coordination.py
services/nex-wc/nex_wc/work_results.py
services/nex-wc/nex_wc/main.py
services/nex-wc/nex_wc/coordination_clients.py
contracts/openapi/nex-wc.openapi.yaml
scripts/smoke/run_p7_s9_postgres_live_golden_b.py
docs/transition/P7/P7_CA01_Source_Backed_WC_Background_Agent_Contract_Closure_v1.0.md
docs/transition/P7/P7_Final_AsBuilt_Baseline_and_P8_Handoff_v1.0.md
```

Then:

```text
1. close work:delegate authorization at WorkItem create;
2. persist metadata-safe authorization evidence;
3. add positive/negative/race/replay tests;
4. update WC OpenAPI;
5. rerun protected authorization tests;
6. rerun P7-S9 Golden B;
7. rerun Repository Full Gate;
8. amend P7 Final As-Built;
9. declare P7 FROZEN only after every CA02 exit item passes.
```

If any source-backed fact differs from this document, stop and create a short CA02 implementation note identifying the discrepancy before changing semantics.
