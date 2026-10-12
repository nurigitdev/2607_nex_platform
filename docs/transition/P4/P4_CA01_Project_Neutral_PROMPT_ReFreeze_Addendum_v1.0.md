# P4-CA01 Project-Neutral IA PROMPT Re-Freeze Addendum v1.0

**Status:** APPROVED / FOCUSED REVALIDATION PASS / RE-FROZEN
**Decision date:** 2026-10-13
**Amendment:** P4-CA01
**Authority layer:** P4 transition controlled amendment over the unchanged v2.1 Frozen baseline

## 1. Decision

P4-CA01 closes the mismatch between project-neutral IA prompt intake and the
Frozen `ExecutionTrigger v2.1` representation.

```text
PROMPT + IA
project_id = null | non-empty string

CLAIMED_WORKITEM
project_id = non-empty string

PA
project_id = non-empty string
```

`project_id=null` means that an authoritative Project has not been resolved for
the IA prompt. It does not create or imply a default, personal, tenant,
Workspace, Conversation, generated, or mock Enterprise OS Project.

## 2. Authority and Preservation

The original files under `docs/frozen/v2.1/` remain byte-for-byte unchanged and
retain their historical hashes. The exact amended contract files under
`P4_CA01_Candidate/` are admitted as the P4-CA01 authority layer despite the
directory's historical name.

Authority for this delta is:

```text
unchanged Integrated Frozen Set
> this P4-CA01 re-freeze addendum
> P4-CA01 amended schema and Python protocol
> P4 v1.1 transition documents
```

The amendment manifest records both the preserved Frozen hashes and the
accepted amendment assets. Silent replacement of Frozen history is forbidden.

## 3. Bounded Contract Delta

The accepted delta:

1. keeps `project_id` explicit and top-level required;
2. permits JSON `null` only where the other trigger constraints admit it;
3. retains `PROMPT -> IA`;
4. retains `CLAIMED_WORKITEM -> CA | PA | EA`;
5. requires a non-empty Project for every claimed-work trigger and every PA;
6. adds equivalent fail-closed Python construction validation;
7. keeps the Step8 trigger vocabulary exactly `PROMPT | CLAIMED_WORKITEM`.

No WC, Enterprise OS, NSL, Project provisioning, default Project, or alternate
IA runtime is introduced.

## 4. Focused Revalidation

| Probe | Result | Evidence |
|---|---|---|
| PROMPT + IA + null Project | PASS | JSON Schema and Python value object accept |
| PROMPT + IA + resolved Project | PASS | both representations accept |
| CLAIMED_WORKITEM + non-empty Project | PASS | both representations accept |
| CLAIMED_WORKITEM + null Project | PASS | both representations reject |
| PROMPT + PA | PASS | both representations reject |
| CLAIMED_WORKITEM + IA | PASS | both representations reject |
| missing TenantId | PASS | both representations reject |
| blank Project | PASS | both representations reject |
| invalid claim generation | PASS | both representations reject |
| Frozen hash preservation | PASS | original schema and protocol hashes unchanged |
| amendment manifest integrity | PASS | byte size and SHA-256 verified |

### E1 impact

The focused E1 probe preserves explicit TenantId, the WC-claim boundary, and
the PA non-null Project invariant. Nullability for IA PROMPT does not weaken
Tenant, principal, actor, AgentIdentity, work/claim, or OA authority boundaries.

### E2E-01 impact

The focused E2E-01 admission probe proves that an IA READ prompt can enter with
`project_id=null` and preserve its source/correlation identity without a fake
Project. This is contract-impact evidence only; it does not claim that the full
AE/CX/NSL runtime scenario was executed in this amendment Slice.

## 5. Evidence

Executable evidence:

```text
scripts/smoke/run_p4_ca01_project_neutral_prompt_closure.py
tests/test_p4_ca01_project_neutral_prompt_closure.py
reports/p4/p4_ca01_project_neutral_prompt_closure.json
```

Integrity evidence:

```text
P4_CA01_Controlled_Amendment_Manifest_v1.0.csv
```

No PostgreSQL or remote model provider is required because P4-CA01 changes only
the trigger contract admission boundary.

## 6. Closure

P4-ISSUE-003 is closed. Canonical P4 source implementation may begin with
P4-S1. P4-ISSUE-026 remains an independent gate that must close before P4-S7.

> **P4-CA01 — CLOSED / RE-FROZEN / OPEN FOR P4 SOURCE IMPLEMENTATION**
