# P9 NeX-WA Privacy Contract Corrective Closure — Codex Work Order v1.0

**Status:** POST-FREEZE BOUNDED CORRECTIVE WORK ORDER  
**Phase:** P9 — NeX-WA Work Evidence / Work Asset Foundation  
**Repository:** `nurigitdev/2607_nex_platform`  
**Branch:** `transition/p4-agent-runtime-foundation`  
**Observed HEAD:** `27e12e23a09bd4b6e3aa557d4e7562f0f0486494`  
**Accepted P9-S30 Executable Baseline:** `bc28307a58b659c791211d995ea773c77ef786c0`  
**Date:** 2026-10-28

---

## 1. Purpose

This work order addresses one bounded implementation defect discovered during
post-P9 GitHub source review and a small number of documentation-consistency
corrections.

The defect is a **privacy contract implementation mismatch**, not an
architecture defect.

P9 architecture, ownership, source-equivalence, completion-barrier,
idempotency, fencing, service topology, database boundaries, and P9.5 deferral
remain unchanged.

Canonical corrective flow:

```text
privacy contract mismatch
→ bounded code correction
→ focused regression
→ protected PostgreSQL/source-authority rerun
→ NeX-WA Slice Gate
→ Repository Full Gate
→ zero-residue verification
→ corrective closure record
→ Final As-Built v1.1
```

---

## 2. Source-Backed Finding

P9 SRS v1.1 requires:

```text
WA classification
= same as authoritative source
or more restrictive

never less restrictive
```

For current P9 sources without an explicit compatible classification:

```text
AE_AGENT_RESULT
AE_ARTIFACT
WC_WORK_RESULT
→ default CONFIDENTIAL
```

The current Artifact path already conforms:

```text
INTERNAL      → CONFIDENTIAL
CONFIDENTIAL  → CONFIDENTIAL
RESTRICTED    → RESTRICTED
```

However current:

```text
services/nex-wa/nex_wa/agent_result_source.py
```

uses hard-coded:

```python
classification="INTERNAL"
```

for:

1. `AE_AGENT_RESULT` PRIMARY WorkEvidence;
2. `AGENT_EXECUTION_RESULT` WorkAsset;
3. `WC_WORK_RESULT` SUPPORTING WorkEvidence.

Therefore:

```text
P9-PF-01
AgentResult / WC supporting evidence classification
does not conform to the SRS v1.1 default.
```

Severity:

```text
P1 — bounded privacy contract conformance defect
```

No Controlled Amendment is required because the intended semantic is already
closed by Contract Closure v1.1 and SRS v1.1.

---

## 3. Required Code Correction

Primary target:

```text
services/nex-wa/nex_wa/agent_result_source.py
```

Required behavior:

```text
AE AgentResult WorkEvidence  → CONFIDENTIAL
Agent WorkAsset              → CONFIDENTIAL
WC WorkResult WorkEvidence   → CONFIDENTIAL
```

Do not change:

```text
WorkEvidence identity
WorkAsset identity
source hash
source equivalence
PRIMARY / SUPPORTING binding
completion barrier
Project verification
Claim lineage
```

Preferred bounded cleanup:

```python
DEFAULT_AGENT_WORK_CLASSIFICATION = "CONFIDENTIAL"
```

or an equivalent local helper.

Do not introduce a new classification-policy subsystem.

---

## 4. Do Not Expand Source Contracts

Current AgentResult and WC WorkResult safe projections do not expose a
classification field.

This corrective Slice SHALL NOT add a new AE/WC API field merely to fix the
current default.

Current rule is sufficient:

```text
source has no compatible classification
→ WA defaults to CONFIDENTIAL
```

A future source classification may later support:

```text
WA classification = max(source classification, CONFIDENTIAL)
```

under the existing no-downgrade invariant.

---

## 5. Required Regression Tests

### 5.1 AgentResult Admission

Update:

```text
tests/test_nex_wa_p9_s17_agent_result_admission.py
```

Add assertions:

```text
IA completed AgentResult
→ PRIMARY WorkEvidence.classification = CONFIDENTIAL
→ Agent WorkAsset.classification       = CONFIDENTIAL

CA/PA/EA completed AgentResult
→ PRIMARY WorkEvidence.classification = CONFIDENTIAL
→ Agent WorkAsset.classification       = CONFIDENTIAL
```

### 5.2 WC Supporting Evidence

Update:

```text
tests/test_nex_wa_p9_s18_wc_supporting_resolution.py
```

Add:

```text
WC_WORK_RESULT SUPPORTING WorkEvidence
→ classification = CONFIDENTIAL
```

Preserve:

```text
one AgentExecution
→ one Agent WorkAsset
→ PRIMARY AgentResult
→ SUPPORTING WorkResult
```

### 5.3 Artifact No-Downgrade

Ensure existing tests prove, or add focused coverage:

```text
Artifact INTERNAL      → CONFIDENTIAL
Artifact CONFIDENTIAL  → CONFIDENTIAL
Artifact RESTRICTED    → RESTRICTED
```

Do not change Artifact semantics.

### 5.4 Protected Persistence Assertion

Extend the existing protected P9 PostgreSQL/source-authority journey so that
persisted rows prove:

```text
AgentResult PRIMARY evidence   = CONFIDENTIAL
Agent WorkAsset                = CONFIDENTIAL
WC WorkResult SUPPORTING       = CONFIDENTIAL
Human Artifact                 >= CONFIDENTIAL
RESTRICTED Artifact            = RESTRICTED when exercised
```

Reuse the existing protected harness; do not create a parallel framework.

---

## 6. Documentation Consistency Correction

Current:

```text
docs/transition/P9/
P9_Final_AsBuilt_Baseline_and_Next_Phase_Handoff_v1.0.md
```

describes the closed path approximately as:

```text
authoritative AE AgentResult / Artifact or WC WorkResult
→ signed reference-only WA intake
```

This can be read as if `WC_WORK_RESULT` were an independent external ingress.

Actual P9 runtime:

```text
External WA intake:
  AE_AGENT_RESULT
  AE_ARTIFACT

Background Agent supporting resolution:
  verified AE AgentResult
  → exact WC lookup by AgentExecution / Claim lineage
  → WC_WORK_RESULT SUPPORTING evidence
```

The Final As-Built successor SHALL describe:

```text
completed AE AgentResult / READY AE Artifact
→ signed reference-only WA intake
→ service-local PostgreSQL JobQueue
→ fenced evidence consumer
→ source projection re-verification

background AgentResult
→ exact WC WorkResult resolution by AgentExecution / Claim lineage
→ SUPPORTING WorkEvidence

→ immutable WorkEvidence
→ bounded WorkAsset / PRIMARY-SUPPORTING binding
```

Explicitly state:

```text
WC WorkResult is not a mandatory independent external WA ingress
in the P9 Foundation.
```

---

## 7. Preserve Historical Closure Records

Do not rewrite accepted historical evidence as though the defect never existed.

Keep v1.0 historical records intact.

Recommended approach:

```text
retain Final As-Built v1.0
+
add post-freeze corrective Slice
+
create Final As-Built v1.1
+
update P9 README to point to v1.1
```

Recommended corrective Slice:

```text
P9-S31A — Privacy Classification Corrective Closure
```

Recommended record:

```text
docs/slices/p9_s31a_privacy_classification_corrective_closure.md
```

This is a conformance correction, not a new feature phase.

---

## 8. Final As-Built Successor

Create:

```text
docs/transition/P9/
P9_Final_AsBuilt_Baseline_and_Next_Phase_Handoff_v1.1.md
```

Do not overwrite v1.0.

v1.1 SHALL:

1. identify the corrected executable commit/tree;
2. state that v1.0 remains the historical P9-S31 freeze;
3. record the privacy classification defect and bounded correction;
4. correct the WC supporting-path wording;
5. record focused/protected/Full Gate results;
6. update evidence hashes;
7. record zero-residue result;
8. preserve `P9.5 = DEFERRED`;
9. preserve `Next Phase = Controlled Decision Required`.

Add final invariant:

```text
AgentResult and WC supporting evidence without an explicit compatible
authoritative source classification default to CONFIDENTIAL.

Artifact classification is preserved or strengthened.

WA never silently downgrades source sensitivity.
```

---

## 9. P9 README Update

Update:

```text
docs/transition/P9/README.md
```

to point to Final As-Built v1.1.

Recommended status:

```text
P9 FOUNDATION CLOSED
P9-CA04 PASS
P9-S31A PRIVACY CORRECTIVE CLOSURE PASS
FINAL AS-BUILT v1.1 FROZEN
```

Do not imply:

```text
new P9 scope
P9.5 activation
next phase authorization
```

---

## 10. No Migration / API Expansion Expected

This correction should require:

```text
database migration          = NO
new table                   = NO
OpenAPI shape change        = NO
JSON Schema field change    = NO
new service                 = NO
new source type             = NO
new Job type                = NO
new scope                   = NO
new authorization model     = NO
```

If any of these become necessary, stop and re-audit before expanding scope.

---

## 11. Required Verification

### Focused Regression

At minimum:

```text
tests/test_nex_wa_p9_s17_agent_result_admission.py
tests/test_nex_wa_p9_s18_wc_supporting_resolution.py
tests/test_nex_wa_p9_s19_human_artifact_admission.py
tests/test_nex_wa_p9_s20_privacy_and_correction.py
```

and directly affected adapter/read-contract tests.

### Protected PostgreSQL / Source Authority

Rerun existing protected P9 acceptance against:

```text
nex_ae_test
nex_wc_test
nex_oa_test
nex_eos_test
nex_wa_test
```

with signed service trust.

Required proof:

```text
completion barrier PASS
AgentResult PRIMARY = CONFIDENTIAL
WC SUPPORTING       = CONFIDENTIAL
Artifact no-downgrade PASS
privacy scopes PASS
cross-tenant denial PASS
zero duplicate evidence PASS
zero owned residue PASS
```

### NeX-WA Slice Gate

Require:

```text
Statement >= 96%
Branch    >= 94%
```

### Repository Full Gate

Run:

```text
scripts/quality/run_quality_gate.sh
```

Require:

```text
exit code = 0
Statement >= 96%
Branch    >= 94%
contract validation PASS
AE Web Node regression PASS
```

Compare with accepted P9-S30 baseline:

```text
pytest             = 18,264 passed, 131 protected skips
statement coverage = 96.01%
branch coverage    = 95.22%
contracts          = 226 / 290 / 244 / 10
```

Any change must be explained.

### Hygiene

Require:

```text
git diff --check PASS
no secrets/tokens/DB URLs in committed evidence
no raw prompt/source body/Artifact bytes in evidence
```

---

## 12. Zero-Residue Requirement

After protected rerun verify:

```text
nex_wa_test  = 0
nex_ae_test  = 0
nex_wc_test  = 0
nex_oa_test  = 0
nex_eos_test = 0
```

Record sanitized counts only.

---

## 13. Suggested Acceptance IDs

```text
P9-PRIV-01
AE_AGENT_RESULT without compatible source classification
→ PRIMARY WorkEvidence = CONFIDENTIAL

P9-PRIV-02
same AgentResult
→ AGENT_EXECUTION_RESULT WorkAsset = CONFIDENTIAL

P9-PRIV-03
WC_WORK_RESULT supporting evidence
→ WorkEvidence = CONFIDENTIAL

P9-PRIV-04
Artifact INTERNAL → CONFIDENTIAL

P9-PRIV-05
Artifact CONFIDENTIAL → CONFIDENTIAL

P9-PRIV-06
Artifact RESTRICTED → RESTRICTED

P9-PRIV-07
basic/detail/audit scopes remain unchanged

P9-PRIV-08
classification correction does not change WorkEvidence identity,
WorkAsset identity, source equivalence, or PRIMARY/SUPPORTING cardinality
```

---

## 14. Identity / Hash Impact

Because `classification` participates in semantic hashes, changing:

```text
INTERNAL
→ CONFIDENTIAL
```

will change:

```text
evidence_hash
asset_hash
```

for newly admitted AgentResult / WC supporting records.

This is expected.

Verify:

```text
deterministic IDs remain stable
semantic hashes change consistently
exact replay after correction remains stable
```

Do not silently migrate historical production WA records in this Slice.

---

## 15. Historical Data / Production Remediation Boundary

Before coding, determine whether real non-test WA evidence exists from the
defective implementation.

If:

```text
no real production/staging WA evidence exists
```

then code correction + regression is sufficient.

If:

```text
real retained AgentResult/WC evidence exists with classification INTERNAL
```

do not silently update it.

Report only non-sensitive aggregate information:

```text
count
environment
source type
classification
```

and request a separate bounded remediation decision.

---

## 16. Non-Goals

Do not introduce:

```text
P9.5 ContributionCandidate
HumanEffortCandidate
AgentEffortCandidate
Scheduler
PA autonomous execution
AUTONOMOUS_HARNESS admission
NSL WA Skills
Skill Pack
WC→WA mandatory event delivery
new message broker
new classification policy engine
HR/payroll data
MM
cost
ledger
Project P/L
```

Current future-PA rule remains:

```text
unknown autonomous execution-authority profile
→ fail closed
→ Controlled Amendment required
```

---

## 17. Recommended Commit Sequence

Prefer one bounded corrective commit after all affected regression passes.

Suggested:

```text
fix(wa): align agent evidence privacy classification
```

If documentation freeze is separated:

```text
fix(wa): align agent evidence privacy classification
docs(wa): freeze P9 privacy corrective closure
```

---

## 18. Definition of Done

```text
[ ] AgentResult PRIMARY defaults to CONFIDENTIAL
[ ] Agent WorkAsset defaults to CONFIDENTIAL
[ ] WC supporting WorkEvidence defaults to CONFIDENTIAL
[ ] Artifact classification preserve/strengthen unchanged
[ ] focused S17/S18/S19/S20 regression PASS
[ ] protected PostgreSQL/source-authority acceptance PASS
[ ] completion/source-equivalence/fencing regressions remain PASS
[ ] privacy scope regressions PASS
[ ] NeX-WA Slice Gate PASS
[ ] Statement >= 96%
[ ] Branch >= 94%
[ ] Repository Full Gate PASS
[ ] contract validation PASS
[ ] AE Web regression PASS
[ ] zero residue PASS
[ ] git diff --check PASS
[ ] P9-S31A corrective closure record committed
[ ] Final As-Built v1.1 committed
[ ] P9 README points to Final As-Built v1.1
[ ] P9.5 remains DEFERRED
[ ] next phase remains NOT implicitly authorized
```

---

## 19. Final Instruction to Codex

Perform this as a **bounded P9 post-freeze corrective closure**.

Do not redesign NeX-WA.

Target state:

```text
Architecture        = unchanged
Service topology    = unchanged
Database schema     = unchanged
API contracts       = unchanged
Source model        = unchanged
Privacy conformance = corrected
Documentation       = reconciled
P9 Foundation       = CLOSED / revalidated
```

The correction is complete when runtime, tests, and Final As-Built all state
the same contract:

> **Agent-executed work and its WC supporting evidence are at least
> CONFIDENTIAL when the authoritative source provides no stronger compatible
> classification; source sensitivity is never silently downgraded.**
