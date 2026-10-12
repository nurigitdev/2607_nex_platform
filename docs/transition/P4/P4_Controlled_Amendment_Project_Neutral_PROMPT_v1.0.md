# P4-CA01 — Project-Neutral IA PROMPT Controlled Amendment Proposal v1.0

**Status:** CONTROLLED AMENDMENT REQUIRED BEFORE P4 CANONICAL ADMISSION
**Target:** NeX Platform v2.1 Frozen `ExecutionTrigger v2.1`

## 1. Problem

Current `execution-trigger-v2.1.schema.json` requires a non-empty `project_id` for every trigger, while Frozen IA intent/context semantics allow a prompt before authoritative Project resolution.

Forbidden workarounds:

- WorkspaceId as ProjectId
- ConversationId as ProjectId
- COMMON/default Project
- generated placeholder Project
- `MOCK_ENTERPRISE_OS`

## 2. Amendment Decision

Keep `project_id` explicit, but allow null for project-neutral IA PROMPT admission.

```text
source_type = PROMPT
agent_type  = IA
project_id  = string | null

source_type = CLAIMED_WORKITEM
agent_type  = CA | PA | EA
project_id  = non-empty string

agent_type = PA
project_id = non-empty string
```

## 3. JSON Schema Delta

Change property:

```json
"project_id": {
  "type": ["string", "null"]
}
```

Keep `project_id` in the top-level required list.

For `CLAIMED_WORKITEM`, conditionally require:

```json
"project_id": {
  "type": "string",
  "minLength": 1
}
```

For `PA`, require non-empty ProjectId.

## 4. Python Protocol Delta

```python
project_id: Optional[str]
```

Validation:

```text
PROMPT + IA
→ None or non-empty string allowed

CLAIMED_WORKITEM
→ None forbidden

PA
→ None forbidden
```

The Python candidate SHALL enforce these conditions at construction or through
a mandatory parser/factory. A type annotation alone is not sufficient focused
revalidation evidence.

## 5. Meaning of null

`project_id = null` means:

> Authoritative Project has not yet been resolved for this IA prompt.

It does not mean personal/default/tenant/workspace Project.

## 6. Impacted Assets

At minimum:

1. Batch02 `execution-trigger-v2.1.schema.json`
2. Batch02 `execution_trigger_v2_1.py`
3. Batch02 README / delta record
4. affected contract tests
5. any Platform AE text that incorrectly says ProjectId is always known at prompt intake
6. amendment manifest/hash

## 7. Focused Revalidation

### E1
- tenant mandatory
- ACTIVE IA server-resolved
- null Project does not weaken Tenant boundary
- PA still requires Project

### E2E-01
- project-neutral IA READ prompt admitted
- RAG/general answer executes without fake Project

### Trigger negatives
- PROMPT + IA + null project → PASS
- PROMPT + IA + valid project → PASS
- CLAIMED_WORKITEM + null project → FAIL
- PA + null project → FAIL
- Tenant missing → FAIL

Step8 trigger vocabulary remains:

```text
ExecutionTrigger = PROMPT | CLAIMED_WORKITEM
```

## 8. Post-Freeze Process

```text
P4-CA01 decision
→ controlled contract amendment
→ focused impact review
→ E1 / E2E-01 / trigger probes
→ amendment manifest/hash
→ re-freeze addendum
```

> **P4-CA01 is a prerequisite to canonical P4 PROMPT admission.**
