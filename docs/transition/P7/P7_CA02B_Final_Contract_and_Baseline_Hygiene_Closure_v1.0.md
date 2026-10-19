# P7-CA02B — Final Contract & Baseline Hygiene Closure v1.0

**Status:** CLOSED / CONTRACT FREEZE APPROVED / P8 ENTRY AUTHORIZED
**Phase:** P7 Final Contract Freeze Hygiene
**Purpose:** Close the remaining contract/document baseline hygiene items before P8 design proceeds
**Predecessor:** P7-CA02 CLOSED / P7-CA02A VERIFIED / Repository Full Gate PASS
**CA02A Verification Commit:** `00fc75c6e0d822b18c9954c803e4c5eaf5fa6794`
**CA02A Verification Tree:** `53ecc42313520858c7e6f5bece7bbc038026f14c`
**CA02B Design Hardening Commit:** `d8d041383b4c402f87f7b4c966d7af46090e2ec9`
**P7 Runtime Implementation Commit:** `67a47f91f0c7c77e816f18c8d3939d3450968b09`
**P7 Runtime Implementation Tree:** `cee757fed13b5d2c2be14536763b75d79b325648`
**Date:** 2026-10-19

---

## 1. Objective

P7 runtime implementation, authority closure, PostgreSQL replay verification,
Golden B, and Repository Full Gate are complete.

The remaining work is limited to three final closure-hygiene items:

```text
1. WC OpenAPI WorkResult schema → actual runtime contract alignment
2. P7 Final As-Built → final repository HEAD / tree baseline clarification
3. P7 Final As-Built header → P7-CA02A VERIFIED status reflected explicitly
```

P7-CA02B SHALL NOT redesign or change P7 runtime semantics.

Target state:

```text
P7 Runtime Freeze   = APPROVED
P7 Contract Freeze  = APPROVED
P7 Baseline Hygiene = CLOSED
P8 Entry            = AUTHORIZED
```

---

## 2. Scope

P7-CA02B is a **contract/documentation closure amendment**.

Allowed:

```text
OpenAPI contract correction
OpenAPI/runtime semantic parity tests
Final As-Built metadata/header correction
README baseline clarification if needed
closure evidence/documentation
```

Not authorized:

```text
Agent runtime redesign
WC state-machine redesign
new authorization semantics
NSL WRITE
Approval
Enterprise OS transaction
new database migration
new provider integration
new WorkItem/Claim/Resume behavior
```

If OpenAPI alignment exposes a real runtime mismatch, stop and record it as a
separate source-backed issue instead of silently changing runtime semantics.

---

## 3. P7-CA02B-DEC-01 — WC OpenAPI WorkResult Schema Must Match Runtime

Current runtime route:

```text
POST /api/v1/work-items/{work_item_id}/results
```

exists and is documented, but the current OpenAPI `WorkResult` schema is weaker
than the effective runtime contract in `nex_wc.work_results.validate_work_result()`.

The OpenAPI SHALL be aligned to the actual runtime contract.

### 3.1 Source of Truth

Read before changing:

```text
services/nex-wc/nex_wc/work_results.py
services/nex-wc/nex_wc/work_result_api.py
services/nex-ae-api/nex_ae_api/work_result_publication.py
docs/transition/P7/contracts/p7-work-result-v2.1.schema.json
contracts/openapi/nex-wc.openapi.yaml
```

Do not invent fields or change runtime only to fit OpenAPI.

The Frozen WorkResult v2.1 document is the generic normative envelope. The P7
WC submission route is an intentionally narrower runtime profile of that
envelope: initial submission is Agent-only, authority lineage is mandatory,
and the WorkItem, Claim, Assignment, and submitting Agent identifiers use the
runtime UUID constraints. CA02B SHALL document this refinement and SHALL NOT
claim that the generic Frozen envelope and the P7 submission profile are
bidirectionally identical.

### 3.2 `submitted_by` Shape

Current OpenAPI incorrectly represents:

```yaml
submitted_by:
  enum: [AGENT]
```

Actual runtime expects an entity-reference object:

```json
{
  "entity_type": "AGENT",
  "entity_id": "<agent-id>"
}
```

Required direction:

```yaml
submitted_by:
  $ref: "#/components/schemas/SubmittedByAgentRef"
```

or equivalent reuse of `EntityRef`, while enforcing:

```text
entity_type = AGENT
entity_id = required
```

Use the actual runtime identifier constraints.

### 3.3 Effective Runtime-Required Fields

The OpenAPI SHALL reflect fields that runtime makes mandatory across syntactic
validation and authority validation.

At minimum inspect and align requiredness of:

```text
schema_version
tenant_id
result_id
work_item_id
revision_no
result_type
schema_ref
technical_outcome
business_outcome
source_execution_ref
claim_ref
claim_generation
assignment_ref
submitted_by
trace
submitted_at
```

Also inspect and classify correctly:

```text
source_plan_ref
summary
payload
artifact_refs
evidence_refs
business_object_refs
```

Do not rely only on `REQUIRED_WORK_RESULT_FIELDS` if later code makes additional
fields mandatory.

### 3.4 Payload Shape

Current OpenAPI constrains:

```text
payload = object | null
```

Compare this with actual runtime validation and the P7 WorkResult contract.
Align OpenAPI to the source-backed accepted shape.

Do not alter production runtime semantics for contract convenience.

### 3.5 Entity References

Inspect exact runtime handling for:

```text
artifact_refs
evidence_refs
business_object_refs
submitted_by
```

and align OpenAPI `EntityRef` use without weakening WC result authority lineage.

### 3.6 Trace Shape

Current OpenAPI represents `trace` only as an object. Runtime validation is
stricter. Add a dedicated `WorkResultTrace` schema, or an equivalent strict
inline schema, that reflects:

```text
additionalProperties = false
correlation_id        = required bounded non-empty string
causation_id          = optional bounded string or null
request_id            = optional bounded string or null
```

Use the runtime maximum length of 128 for all three identifiers. Do not reuse
a broader trace component if doing so weakens these constraints.

### 3.7 P7 Submission Profile Conformance

The OpenAPI contract SHALL describe the accepted P7 submission profile, not
expand the route to every shape permitted by the generic Frozen envelope.

Required conformance direction:

```text
valid P7 WorkResult fixture
-> accepted by Frozen generic contract
-> accepted by P7 runtime validator
-> accepted by WC OpenAPI submission profile
```

OpenAPI/runtime parity tests SHALL cover the authority-bearing fields and
strict trace shape. Optional generic metadata that is not an authority input
must retain the Frozen contract constraints unless a separately documented
runtime defect requires correction. Frozen v2.1 source documents remain
unchanged.

---

## 4. P7-CA02B-DEC-02 — Strengthen Runtime/OpenAPI Semantic Parity Tests

Existing CA02 parity tests prove route presence and response inventory. CA02B
SHALL add schema-level semantic parity.

Minimum assertions:

```text
submitted_by is an object, not a string enum
submitted_by.entity_type is constrained to AGENT
runtime-required WorkResult fields are OpenAPI-required
claim_generation has correct integer minimum
work_item_id / claim_ref / assignment_ref identifier shapes are compatible
WorkResult wrapper requires expected_version + work_result
trace requires correlation_id and rejects unsupported properties
trace identifiers use the runtime 128-character bound
```

Preferred test:

```text
one valid WorkResult fixture
→ accepted by runtime validator
→ accepted by OpenAPI schema validator (if existing utility supports it)
```

Reuse existing validation utilities. Do not create another general contract
validation framework.

---

## 5. P7-CA02B-DEC-03 — Distinguish Runtime, Verification, and Contract Baselines

Before CA02B, P7 has two legitimate revision identities:

```text
Runtime implementation closure:
  commit = 67a47f91f0c7c77e816f18c8d3939d3450968b09
  tree   = cee757fed13b5d2c2be14536763b75d79b325648

Verification closure baseline after CA02A and before CA02B:
  HEAD   = 00fc75c6e0d822b18c9954c803e4c5eaf5fa6794
  tree   = 53ecc42313520858c7e6f5bece7bbc038026f14c
```

The Final As-Built SHALL explicitly distinguish them and SHALL NOT call the
CA02A baseline the final repository baseline after CA02B.

Recommended section:

```text
P7 Runtime Implementation Baseline
----------------------------------
runtime_source_revision = 67a47f91...
runtime_tree_digest     = cee757fe...

P7 CA02A Verification Closure Baseline
--------------------------------------
verification_closure_commit  = 00fc75c6...
verification_repository_tree = 53ecc423...

P7 CA02B Contract Closure
-------------------------
ca02b_contract_closure_ref = Git commit containing the CA02B closure
```

P8 SHALL start from the CA02B closure commit, or a verified descendant, while
preserving both the runtime implementation and CA02A verification provenance.
The exact CA02B commit and tree SHALL be reported after commit creation and
verified through Git history; a tracked document SHALL NOT attempt to embed
the hash of the commit or tree that contains itself.

---

## 6. P7-CA02B-DEC-04 — Evidence Provenance Terminology

Do not rewrite valid historical JSON evidence.

Document the distinction:

```text
source_revision_under_test
= runtime source revision actually exercised

tested_tree_digest
= runtime tree exercised by protected test

final_closure_commit
= closure commit associated with that evidence generation

verification_closure_commit
= CA02A verification-only closure commit preceding CA02B

ca02b_contract_closure_ref
= Git commit containing the finalized CA02B closure
```

For phase-level Final As-Built, prefer:

```text
runtime_source_revision
runtime_tree_digest
verification_closure_commit
verification_repository_tree
ca02b_contract_closure_ref
```

`ca02b_contract_closure_ref` means the Git commit containing the finalized
CA02B contract, tests, and closure documents. Its resolved commit/tree identity
is recorded by the commit/push result or an external release attestation, not
self-embedded into the tracked tree.

If historical evidence retains `final_closure_commit`, explain its scope rather
than modifying accepted evidence.

---

## 7. P7-CA02B-DEC-05 — Final As-Built Header Must Include CA02A VERIFIED

Update the Final As-Built status header from the current form to one that
explicitly includes CA02A verification.

Recommended:

```text
FINAL / P7 CLOSED / P7-CA02 CLOSED / P7-CA02A VERIFIED / P7-CA02B CLOSED / P8 ENTRY AUTHORIZED
```

or, if consistent with existing wording:

```text
FINAL / P7 FROZEN / CA02 CLOSED / CA02A VERIFIED / CA02B CLOSED / P8 ENTRY AUTHORIZED
```

Use one consistent form across:

```text
docs/transition/P7/P7_Final_AsBuilt_Baseline_and_P8_Handoff_v1.0.md
docs/transition/P7/README.md
```

Do not imply that P8 implementation has already begun.

---

## 8. Final As-Built Baseline Identity Section

Add near the top of the Final As-Built:

```markdown
## Final Baseline Identity

P7 runtime implementation:
- Commit: `67a47f91...`
- Tree: `cee757fe...`

P7 CA02A verification closure baseline:
- Commit: `00fc75c6...`
- Tree: `53ecc423...`

CA02A changes verification/test/documentation evidence only and does not
change P7 production runtime semantics.

P7 CA02B contract closure:
- Reference: the Git commit containing this finalized section
- P8 entry: that commit or a verified descendant
- Resolution: Git history or external release attestation; no self-embedded hash
```

This becomes the explicit baseline identity inherited by P8.

---

## 9. README Alignment

Review:

```text
docs/transition/P7/README.md
```

Ensure consistent state:

```text
P7 CLOSED
P7-CA02 CLOSED
P7-CA02A VERIFIED
P7-CA02B CLOSED
P8 ENTRY AUTHORIZED
```

If revisions are mentioned, use the same runtime/final-baseline distinction as
the Final As-Built.

README document order SHALL include this CA02B amendment and the CA02B Slice
closure record before the Final As-Built handoff document.

---

## 10. Required Tests

Focused:

```text
1. WC OpenAPI path parity
2. WC WorkResult schema semantic parity
3. current WorkResult runtime validation tests
4. existing CA02 authorization tests
5. contract validation
```

Recommended affected regression:

```text
tests/test_nex_wc_*
tests/test_ae_wc_p7_*
tests/test_platform_*contract*
```

Use current repository naming and utilities.

---

## 11. Full Gate Policy

Because this amendment changes a public API contract and final phase baseline,
run Repository Full Gate after focused tests.

Required:

```text
Repository Full Gate = PASS
statement coverage >= repository threshold
branch coverage >= repository threshold
contract validation = PASS
AE Web tests = PASS
```

The CA02B Full Gate counts and coverage SHALL be added to the Final As-Built
closure verification table. They SHALL be labeled as CA02B results rather than
silently replacing the historical CA02A evidence rows.

No live MO/provider rerun is required unless production runtime source changes.

No PostgreSQL replay rerun is required unless persistence/runtime source changes.

Existing accepted evidence remains valid:

```text
CA02 negative PostgreSQL
CA02A PostgreSQL replay
S8 recovery
S9 live Golden B
```

---

## 12. No Runtime Semantics Change Rule

Expected production source changes:

```text
none
```

Expected modified areas:

```text
contracts/openapi/nex-wc.openapi.yaml
tests/... OpenAPI/contract parity tests
docs/transition/P7/P7_Final_AsBuilt_Baseline_and_P8_Handoff_v1.0.md
docs/transition/P7/README.md
docs/slices/p7_ca02b_final_contract_baseline_hygiene_closure.md
```

If `services/nex-wc/...` production source changes become necessary, stop and
record why OpenAPI alignment exposed a runtime defect.

---

## 13. Closure Checklist

P7-CA02B SHALL close only when:

```text
[x] WC OpenAPI submitted_by matches runtime object shape
[x] submitted_by.entity_type = AGENT enforced
[x] all effective runtime-required WorkResult fields are OpenAPI-required
[x] payload shape reconciled source-backed
[x] EntityRef constraints reconciled
[x] trace shape, required correlation_id, bounds, and additionalProperties reconciled
[x] P7 submission profile is documented as a narrower Frozen profile
[x] WorkResult wrapper parity verified
[x] runtime/OpenAPI semantic parity tests PASS
[x] contract validation PASS
[x] Final As-Built header includes CA02A VERIFIED
[x] Final As-Built records runtime commit/tree
[x] Final As-Built records CA02A verification commit/tree with precise terminology
[x] Final As-Built identifies the non-self-referential CA02B closure ref
[x] Final As-Built records CA02B Full Gate results separately
[x] README status matches Final As-Built
[x] README read order includes CA02B amendment and closure Slice
[x] Repository Full Gate PASS
[x] no production runtime semantic change
```

---

## 14. Final P7 Status

After CA02B:

```text
P7 Runtime Architecture   = CLOSED
P7 Authority Chain        = CLOSED
P7 Reliability            = CLOSED
P7 Golden B               = CLOSED
P7-CA02                    = CLOSED
P7-CA02A                   = VERIFIED
P7-CA02B                   = CLOSED
P7 Contract Freeze        = APPROVED
P7 Final Baseline         = FROZEN
P8 Entry                   = AUTHORIZED
```

---

## 15. Suggested Commit Sequence

One or two commits should be sufficient:

```text
fix(api): align WC WorkResult OpenAPI with runtime
docs(p7): freeze final P7 contract and baseline identity
```

Optional if test changes are significant:

```text
test(p7): enforce WC WorkResult contract parity
```

---

## 16. Codex Execution Instruction

Implement P7-CA02B as a final contract/baseline hygiene closure.

Start by reading:

```text
services/nex-wc/nex_wc/work_results.py
services/nex-wc/nex_wc/work_result_api.py
services/nex-ae-api/nex_ae_api/work_result_publication.py
contracts/openapi/nex-wc.openapi.yaml
docs/transition/P7/contracts/p7-work-result-v2.1.schema.json
docs/transition/P7/P7_Final_AsBuilt_Baseline_and_P8_Handoff_v1.0.md
docs/transition/P7/README.md
docs/slices/p7_ca02a_postgresql_replay_evidence_closure.md
```

Then:

```text
1. derive the effective runtime WorkResult contract from source;
2. document the narrower P7 submission profile and align WC OpenAPI to it;
3. strengthen runtime/OpenAPI semantic parity tests;
4. enforce the strict runtime trace shape in OpenAPI and parity tests;
5. run focused WC/contract regression;
6. update Final As-Built status to include CA02A VERIFIED;
7. add explicit runtime and CA02A verification baseline identities;
8. identify CA02B through the containing Git commit without self-reference;
9. align P7 README status and read order;
10. run Repository Full Gate and record CA02B results separately;
11. add a short CA02B closure Slice record;
12. declare P7 Contract Freeze approved.
```

Do not modify Frozen v2.1 source documents.

Do not change production runtime semantics merely to make OpenAPI validation pass.

---

## 17. Implementation Closure

P7-CA02B aligned only the public WC OpenAPI submission profile, parity tests,
and final P7 closure documents. No production runtime source, database schema,
persistence behavior, or provider integration changed.

```text
semantic parity tests = 35 passed
affected regression  = 263 passed, 6 skipped
contract validation  = 174 schemas, 236 examples, 204 negative, 8 OpenAPI
repository Full Gate = 15,442 passed, 48 skipped
statement coverage   = 96.83% (threshold 95%)
branch coverage      = 96.22% (threshold 85%; P7 policy 94% satisfied)
AE Web tests         = 331 passed, 0 failed, 0 skipped
```

The skipped tests are existing opt-in protected smokes. No CA02B-required test
was skipped. PostgreSQL and remote-provider evidence were not rerun because
CA02B changed neither production runtime nor persistence source.
