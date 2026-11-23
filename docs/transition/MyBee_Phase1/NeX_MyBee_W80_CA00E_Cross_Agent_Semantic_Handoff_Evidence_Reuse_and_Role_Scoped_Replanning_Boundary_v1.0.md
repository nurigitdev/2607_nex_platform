# NeX MyBee W80-CA00E Cross-Agent Semantic Handoff, Evidence Reuse, and Role-Scoped Replanning Boundary v1.0

**Status:** DESIGN FROZEN / IMPLEMENTATION PENDING

**Predecessor:** W80-CA00D

**Boundary:** IA semantic admission -> WC delegation -> claimed target-Agent planning

**Database migration:** None planned; reuse existing AE semantic evidence,
WorkIntent, AgentContext, AgentExecution, and claimed-planning-source storage

## 1. Purpose

The installed M1 journey proved that one user request currently invokes the
generation provider for `INTENT -> CONTEXT -> PLAN` in IA and repeats the same
three semantic stages after WC delivers the claimed WorkItem to PA. The two
Agent roles are legitimately different, but the current implementation reuses
one semantic pipeline and selects a PLAN profile by capability alone. In the
accepted live evidence, the IA and PA PLAN candidates for each request had the
same candidate hash and both proposed one `DELEGATE_WORK` step.

W80-CA00E does not optimize one M1 fixture or one finance intent. It defines a
general cross-Agent semantic handoff boundary for arbitrary IA prompts and for
future PA, CA, and EA delegation. The objective is to preserve admitted
semantic facts when they remain trustworthy, rebuild target-Agent authority
context, and generate only the plan owned by the receiving Agent role.

Generation-call reduction is an expected consequence of correct evidence
reuse. It is not the admission criterion.

## 2. Source-Backed Findings

1. `BackgroundAgentPlanningService` converts the claimed planning source into
   a new prompt and calls the same semantic admission service used by IA.
2. `DeterministicCandidateAdmissionService` executes INTENT, CONTEXT, and PLAN
   for both `IA_PROMPT` and `CLAIMED_WORKITEM`.
3. A claimed WorkIntent ultimately takes its capability, goal, work class,
   Project, result contract, and typed business context from the durable WC
   planning source. Provider output is not the authority for those fields.
4. The claimed-work context resolver already distinguishes DOCUMENT, ANALYSIS,
   grounded evidence, and general-answer profiles.
5. Claimed planning source v1/v2 carries goal, capability, Project, artifact,
   evidence, completion, and optional typed business context, but it does not
   carry immutable references to the parent's admitted WorkIntent and semantic
   stage evidence.
6. `PlanCandidateProfileRegistry` resolves a prompt profile by capability ID
   alone. It cannot distinguish an IA delegation plan from a PA product
   preparation or claimed-work execution plan.
7. M1 live evidence recorded two requests, four semantic admissions, and
   twelve generation calls. The PA-side INTENT and CONTEXT calls consumed about
   101 seconds per request on the observed Qwen3.5-9B deployment.

## 3. Non-Goals

W80-CA00E does not:

- bypass IA intent admission for arbitrary user prompts;
- reuse an IA AgentContext as a PA, CA, or EA AgentContext;
- make provider output authoritative for OA, WC, EOS, Project, evidence, or
  attachment access;
- reuse an IA delegation PLAN as a target-Agent execution PLAN;
- introduce M1-, tenant-, Project-count-, ratio-, or fixture-specific routing;
- remove the current full semantic pipeline compatibility path;
- change the NSL compiler/runtime, product business APIs, or model revision;
- add a parallel queue, result pipeline, or semantic evidence store.

## 4. Agent Responsibility Boundary

### 4.1 IA

IA owns conversational interpretation:

- raw-prompt admission and conversation-aware intent resolution;
- clarification and multi-intent separation;
- user-facing entity and parameter candidate admission;
- Project or domain target selection;
- the decision to answer locally or delegate;
- a `DELEGATION` PLAN when delegation is required.

### 4.2 Receiving Agent

PA, CA, or EA owns claimed-work execution:

- parent evidence integrity and compatibility verification;
- fresh target-Agent identity and capability admission;
- current OA, WC, EOS, Project, attachment, and evidence authorization;
- target-role context construction;
- `CLAIMED_WORK_EXECUTION` or `PRODUCT_PREPARATION` planning;
- result production under the delegated result contract.

The receiving Agent must not reinterpret a valid delegated capability merely
to reproduce the IA classification. It must not trust upstream semantic facts
as current business authority.

## 5. Semantic Handoff Contract

The claimed planning source must gain a versioned, hash-bound semantic handoff
projection. A v3 internal contract is preferred over changing v1/v2 semantics.
The projection must contain references, not duplicated raw candidate payloads:

```text
semantic_handoff.schema_version
semantic_handoff.tenant_id
semantic_handoff.owner_subject_id
semantic_handoff.parent_execution_id
semantic_handoff.parent_agent_type
semantic_handoff.parent_work_intent_id
semantic_handoff.parent_work_intent_hash
semantic_handoff.parent_intent_revision
semantic_handoff.intent_candidate_id
semantic_handoff.intent_candidate_hash
semantic_handoff.intent_evidence_hash
semantic_handoff.context_candidate_id
semantic_handoff.context_candidate_hash
semantic_handoff.context_evidence_hash
semantic_handoff.source_type
semantic_handoff.source_ref
semantic_handoff.source_interaction_id
semantic_handoff.source_revision
semantic_handoff.created_at
semantic_handoff.handoff_hash
```

The parent execution ID already present in the business delegation lineage
remains the root reference. AE must resolve all referenced records from its own
authoritative repositories and compare every hash. WC transports the immutable
projection but cannot manufacture or upgrade AE semantic evidence.

Raw prompt, conversation content, candidate payloads, secrets, and binary
attachments are not copied into the handoff projection. Their existing private
storage and diagnostic-retention rules remain unchanged.

## 6. Evidence Reuse Decision

A reusable-evidence evaluator must return one deterministic decision:

```text
REUSE_INTENT_REBUILD_CONTEXT
REUSE_INTENT_AUGMENT_CONTEXT
FULL_SEMANTIC_REPLAN
RETURN_FOR_CLARIFICATION
DENY_AUTHORITY_CHANGE
DENY_CONFLICT
```

It must record one or more bounded reason codes:

```text
MISSING
STALE
LOW_CONFIDENCE
AUTHORITY_CHANGED
SCHEMA_DRIFT
CONFLICT
SUPERSEDED
SCOPE_MISMATCH
CAPABILITY_MISMATCH
HASH_MISMATCH
UNSUPPORTED_AGENT_ROLE
```

### 6.1 Reuse requirements

INTENT evidence may be reused only when:

- parent execution, WorkIntent, candidate, and evidence hashes are intact;
- tenant, requester lineage, source revision, and delegated capability match;
- the WorkIntent has not been superseded;
- candidate and evidence schema versions are admitted;
- confidence satisfies the registered reuse policy;
- clarification is not pending;
- the receiving Agent type supports the delegated work class and capability.

### 6.2 Context rule

The parent AgentContext object is never reused. Semantic selectors and typed
input context may be adopted as non-authoritative candidates, but the receiving
Agent must build a new AgentContext with its own identity and fresh authority.
OA decisions, Project state, Project Agent state, artifact/evidence access, and
retrieval authorization are always resolved again.

### 6.3 Fallback rule

`MISSING`, `STALE`, `LOW_CONFIDENCE`, compatible `SCHEMA_DRIFT`, or a
superseded semantic revision may enter the existing full INTENT, CONTEXT, PLAN
pipeline when the registered policy permits it.

`AUTHORITY_CHANGED`, `SCOPE_MISMATCH`, `CAPABILITY_MISMATCH`, `HASH_MISMATCH`,
and security-relevant `CONFLICT` cannot be repaired by another LLM call. They
must fail closed or return to IA for clarification/revision. Provider fallback
must never override authoritative denial.

## 7. Prompt and Work-Class Matrix

| Input or work type | Required behavior |
|---|---|
| IA-only general conversation | Existing IA path; no claimed-Agent handoff |
| IA Chat/RAG grounded answer | Existing IA retrieval and answer path unless an admitted delegation is created |
| Structured Project operation | Reuse admitted intent; rebuild authority context; generate target-role plan |
| Delegated document generation | Reuse compatible intent; revalidate sources and attachment access; generate document plan |
| Delegated analysis or summary | Reuse compatible intent; refresh evidence authorization and as-of state; generate analysis plan |
| Unstructured delegated goal | Reuse only compatible high-level intent; augment context or run full target semantic planning |
| Ambiguous prompt | Clarify in IA before delegation; do not reuse unresolved evidence |
| Multi-intent prompt | Split into independently versioned WorkIntents and handoffs |
| User correction or follow-up | Supersede affected evidence and resume from the earliest invalid stage |
| Low-confidence or incompatible evidence | Full semantic replan or IA clarification according to registered policy |
| Revoked authority or inactive Project/Agent | Fail closed without provider-based repair |

## 8. Role-Scoped Planning Profiles

Plan profile identity must be expanded from capability-only lookup to the
following immutable key:

```text
capability_id
planning_source_type
agent_type
planning_purpose
```

Initial planning purposes are:

```text
INTERACTION_RESPONSE
DELEGATION
CLAIMED_WORK_EXECUTION
PRODUCT_PREPARATION
RESULT_SYNTHESIS
```

IA Project routing uses `DELEGATION`. A claimed PA does not select that profile
again; it selects `PRODUCT_PREPARATION` or `CLAIMED_WORK_EXECUTION` according to
the installed product coordinator. Missing exact registrations must use an
explicit compatibility profile or fail closed. They must not silently fall
back to a profile registered for another Agent role or planning purpose.

Profile registrations remain product-neutral. A registration may reference a
capability, Agent role, and purpose, but cannot embed business values, Project
IDs, tenant IDs, fixed ratios, or scenario payloads.

## 9. Compatibility and Persistence

1. Claimed planning source v1/v2 remain readable and use the current full
   semantic pipeline unless a verified parent lineage can be resolved.
2. New handoffs use a versioned v3 projection with semantic evidence refs.
3. Existing AE semantic candidate, WorkIntent, AgentContext, AgentExecution,
   and WC planning-source JSON persistence are reused.
4. No relational table is added. A migration is forbidden unless a source and
   storage-fit audit proves that existing JSON persistence cannot preserve the
   contract atomically.
5. Replay returns the original reuse decision and target plan identity when all
   hashes and authority versions remain equal.
6. Restart, redelivery, and ACK loss must not trigger duplicate provider calls
   after a semantic stage has durable admitted evidence.
7. Diagnostic evidence records reuse decision, reason codes, source and target
   execution IDs, stage hashes, and latency, but ordinary logs remain
   content-safe.

## 10. Security and Privacy

- upstream semantic evidence is input evidence, not authorization;
- cross-tenant, cross-requester, cross-Project, and cross-capability reuse is
  forbidden;
- raw prompt and private candidate content stay in their existing owner-private
  or restricted diagnostic boundary;
- attachment and retrieval evidence are reauthorized for the target Agent;
- stale OA decisions or inactive Project/Agent state fail closed;
- reuse decisions and fallback reasons are bounded operational metadata;
- provider regeneration cannot convert denied authority into allowed authority.

## 11. Recommended Implementation Slices

### W80-CA00E.1 - Semantic Handoff Inventory and v3 Contract

Freeze parent-lineage fields, repository resolution, compatibility behavior,
and residue guards. Prove that no M1 fixture or business value enters the
contract.

### W80-CA00E.2 - Evidence Reuse Evaluator

Implement hash, schema, confidence, revision, scope, capability, and freshness
decisions with the bounded outcomes and reason codes in Section 6.

### W80-CA00E.3 - Target-Agent Context Rebuild

Adopt reusable semantic candidates while always reconstructing target identity,
OA/WC/EOS authority, Project state, and artifact/evidence access.

### W80-CA00E.4 - Role-Scoped Planning Profile Registry

Introduce the four-part profile key, separate IA delegation from target-Agent
execution/product preparation, and preserve explicit compatibility profiles.

### W80-CA00E.5 - Fallback, Replay, and Restart Hardening

Connect safe full-pipeline fallback, clarification return, authority denial,
durable stage replay, ACK-loss recovery, and provider-call deduplication.

### W80-CA00E.6 - Protected Acceptance and Live Confirmation

Run the prompt/work-class matrix, actual AE/WC/OA/EOS PostgreSQL protected
tests, live generation evidence, installed journey replay, coverage gates, and
Repository Full Gate. Compare call count and latency without making performance
the correctness criterion.

## 12. Acceptance Matrix

The implementation cannot close on the M1 Golden Scenario alone. It must cover:

1. general answer, grounded answer, document summary, and document generation;
2. structured and unstructured delegated work;
3. PA, CA, and EA target roles where currently admitted;
4. conversation follow-up, correction, supersession, and multi-intent split;
5. artifact and retrieval evidence authorization changes;
6. low confidence, stale evidence, missing evidence, and schema drift;
7. cross-tenant, cross-requester, cross-Project, and hash-tamper denial;
8. OA revocation, inactive Project, and inactive target Agent denial;
9. exact replay, restart, event redelivery, and ACK loss;
10. no provider call on an exact durable replay;
11. no delegation profile selected for claimed execution planning;
12. source scans excluding fixture, demo, M1 payload values, fixed Project
    counts, and tenant-specific dictionaries from product runtime code.

## 13. Closure Criteria

```text
IA PROMPT BREADTH                    = PRESERVED
UPSTREAM INTENT REUSE               = POLICY- AND EVIDENCE-GOVERNED
TARGET AGENT CONTEXT REUSE          = FORBIDDEN
TARGET AUTHORITY REVALIDATION       = REQUIRED
ROLE-SCOPED PLAN PROFILE            = REQUIRED
AUTHORITY DENIAL PROVIDER OVERRIDE  = FORBIDDEN
FULL SEMANTIC FALLBACK              = PRESERVED WHEN SAFE
V1/V2 CLAIMED SOURCE COMPATIBILITY  = PRESERVED
M1/FIXTURE-SPECIFIC PRODUCT LOGIC   = FORBIDDEN
NEW RELATIONAL STORAGE              = NOT PLANNED
```

W80-CA00E closes only after the generalized acceptance matrix passes and an
installed live replay proves that the receiving Agent produces a role-correct
plan. A lower provider-call count without those proofs is not acceptance.
