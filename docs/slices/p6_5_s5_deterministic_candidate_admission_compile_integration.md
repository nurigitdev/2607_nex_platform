# P6.5-S5 Deterministic Candidate Admission / Compile Integration

**Status:** IMPLEMENTED
**Date:** 2026-10-17
**Predecessor:** P6.5-S4 Live Plan Candidate Generation

## Scope

P6.5-S5 composes the three live semantic stages with the existing P5
deterministic planning pipeline:

```text
Prompt
-> IntentCandidate
-> WorkIntent
-> ContextCandidateSet
-> AgentContext
-> PlanCandidate
-> AgentPlan
-> PlanValidation
-> ExecutablePlan
```

The LLM remains a bounded suggestion source. It cannot bypass trusted AE
resolution, PlanValidation, exact capability binding, or the deterministic
compiler. Required mode never silently falls back to the compatibility
generation path.

## Persistence Boundary

Migration `2300_ae_semantic_candidate` adds the bounded
`ae_semantic_candidate` evidence table. Its identity is:

```text
(tenant_id, candidate_id)
(tenant_id, agent_execution_id, semantic_stage, candidate_revision) UNIQUE
```

The table stores owner scope, exact execution/stage/revision lineage, candidate
hash, opaque storage reference and size, prompt/model lineage, admission policy,
directive, failure code, and immutable evidence JSON. It does not store raw
prompt text, raw provider output, hidden reasoning, or candidate content.

Candidate JSON is canonicalized and stored in owner-private content-addressed
storage under the `ae://semantic-candidates/` reference scheme. Memory,
filesystem, and S3-compatible adapters share the same immutable integrity
contract. Required mode rejects in-memory storage at startup; it requires
filesystem or S3-compatible durable private storage.

## Deterministic Admission And Replay

Stable UUIDv5 identities are derived from the AgentExecution for WorkIntent,
AgentContext, AgentPlan, PlanValidation, ExecutablePlan, compiled steps, and the
three candidate revisions. A first execution calls the provider once per stage,
persists candidate payload before evidence, creates canonical records, validates
the plan, and compiles only after `VALID`.

Retry or restart loads the exact evidence and owner-private payload, verifies
tenant/owner/execution/stage/revision lineage, and reconstructs a missing
canonical WorkIntent, AgentContext, or AgentPlan without another provider call.
Missing or altered payloads, conflicting evidence, calibration absence, hash or
storage-reference mismatch, and disappearing AgentExecution all fail closed.

## Chat Runtime Boundary

`NEX_AE_PLANNING_MODE` supports `disabled`, `shadow`, and `required` profiles.

- `disabled` preserves the existing Chat/RAG compatibility path.
- `shadow` may observe the semantic boundary but cannot replace compatibility
  execution or make model output authoritative.
- `required` performs deterministic admission and returns HTTP 202 with a
  sanitized `PENDING` semantic-planning projection after compile acceptance.
  It does not invoke direct CX generation.

The runtime obtains the latest tenant capability snapshot or creates the
deterministic version-1 snapshot, derives trusted retrieval references from the
authorized package, and excludes provider endpoints, secrets, raw candidate
content, and raw prompt text from the response projection.

S5 deliberately does not create RuntimeJob or execute LOCAL_SKILL. The P6.5
plan assigns provider/adversarial hardening to S6 and the actual PostgreSQL plus
remote-provider golden journey, including the preferred RuntimeJob extension,
to S7.

## Prompt Registry PostgreSQL Parity

The actual PostgreSQL smoke found that SQL-backed Prompt Registry reads omitted
`service_id` and `purpose`, while the in-memory store returned them. The SQL
version loaders now join `ae_prompt_templates`, preserving the same binding
validation contract in both stores. Regression tests pin this parity.

## Protected Evidence

Actual `nex_ae_test` smoke executed migration discovery and the complete
three-stage deterministic fixture through real PostgreSQL:

```text
database/role = nex_ae_test / nex_ae_user
latest migration = 2300_ae_semantic_candidate
semantic candidates = 3
provider calls = INTENT, CONTEXT, PLAN exactly once
restart provider calls = 0
canonical rows = one per identity
database residue after cleanup = 0
private-storage residue after cleanup = 0
checks = 12/12 PASS
```

Protected live stage smoke used the actual MO route and DGX generation provider
for INTENT, CONTEXT, and PLAN. All stages selected the exact
`general-llm-default / Qwen3.5-4B` lineage and model-specific calibration, then
continued only after deterministic admission:

```text
INTENT checks = 10/10 PASS
CONTEXT checks = 11/11 PASS
PLAN checks = 13/13 PASS
```

The threshold used by protected smoke remains provisional test calibration; it
is not presented as production calibration. Sanitized combined evidence is in
`reports/live/p65-s5-deterministic-admission-evidence.json`.

## Verification

```text
S5 focused tests: 89 passed
Focused admission/evidence coverage: 99% total, 99% branch-oriented result
Affected P4/P5/P6/P6.5 regression: 830 passed, 5 protected-smoke skips
Actual PostgreSQL smoke: PASS, 12/12 checks, no skip
AE Slice Gate: PASS, 4,310 passed, 10 protected-smoke skips
AE Slice Gate statement coverage: 98.62%
AE Slice Gate branch coverage: 96.82% (previous level preserved)
Full Checkpoint Gate: PASS, 14,375 passed, 37 protected-smoke skips
Full Checkpoint statement coverage: 98.99%
Full Checkpoint branch coverage: 97.58%
Contract validation: PASS, 174 schemas, 236 examples,
204 negative examples, 7 OpenAPI documents
Protected live provider stages: PASS, 34/34 checks
```

The protected skips in generic gates are existing opt-in database/live tests.
The S5 PostgreSQL and provider checks were enabled and executed separately; the
S5 PostgreSQL evidence explicitly records `execution_state=EXECUTED`.

## Exit

P6.5-S5 is closed when one AgentExecution can deterministically admit and
compile the three semantic candidates, preserve exact prompt/model/candidate
lineage, resume without semantic regeneration, and prevent executable work
before valid deterministic compilation. P6.5-S6 may now harden the provider,
candidate, security, and privacy failure matrix without changing this authority
boundary.
