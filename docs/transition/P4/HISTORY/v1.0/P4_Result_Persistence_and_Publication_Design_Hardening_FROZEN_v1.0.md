# P4 Result Persistence and Publication Design Hardening FROZEN v1.0

> **SUPERSEDED:** Historical P4 v1.0 record. Use the v1.1 baseline in the P4 parent directory.

**Process Step:** STEP 8.1
**Status:** P4 TRANSITION DESIGN BASELINE - FROZEN
**Scope:** P4 AgentResult persistence, required ResultDelivery, IA workspace
publication, completion safety, and transition evidence
**Higher Authority:** NeX Platform v2.1, Agent v2.1, NSL v0.2 Frozen Set
**SRS:** `P4_Agent_Runtime_Foundation_SRS_v1.0.md`
**Frozen Change:** NONE

## 1. Purpose

This document closes implementation-level gaps found while reviewing the P4
SRS against the Frozen AgentResult and Result Publication contracts.

It fixes the P4 design for:

1. complete AgentResult reconstruction;
2. atomic result and required-delivery persistence;
3. delivery-plan completeness before success;
4. minimally conformant IA `WORKSPACE_RESULT` publication;
5. deterministic `result_hash` calculation;
6. audit, issue, and test traceability.

This is a transition implementation decision. It does not edit or replace the
Frozen product architecture.

## 2. Non-Negotiable Invariants

```text
AgentResult != GeneratedResponse
AgentResult != ResultDelivery
BusinessOperationId != PublicationOperationId
legacy Chat COMPLETED != canonical AgentExecution SUCCEEDED
```

Canonical `AgentExecution.SUCCEEDED` requires all of the following:

```text
AgentResult is durably stored
AND the required delivery plan is complete and valid
AND every required ResultDelivery is durably ACKNOWLEDGED
```

An empty delivery collection is never sufficient evidence of completion.

## 3. Decision P4-HDN-001: Complete AgentResult Persistence

P4 shall preserve the complete JSON object validated by
`agent-result-v2.1.schema.json`.

The AE PostgreSQL representation shall use both:

- normalized columns required for identity, filtering, joins, and transition
  guards; and
- one immutable `result_envelope_json` JSONB value containing the complete
  canonical AgentResult envelope.

The additive physical profile shall include at least:

```text
schema_version
tenant_id
result_id
agent_execution_id
agent_type
status
quality
result_hash
source claim lineage fields
created_at
structured_result_json
result_envelope_json
```

`structured_result_json` shall equal the `structured_result` member of
`result_envelope_json`. Normalized identity, status, lineage, hash, and time
columns shall equal the corresponding envelope values.

The repository shall validate this projection parity on write and on protected
read/smoke paths. A row that cannot reconstruct a schema-valid AgentResult is
invalid.

The envelope shall preserve required fields including:

```text
business_refs
artifact_refs
evidence_refs
warnings
conflicts
provenance
```

and all optional fields that are present in the canonical result.

Private response bodies, raw prompts, credentials, provider secrets, and raw
evidence shall not be copied into the envelope when stable private-storage
references and content hashes already exist.

## 4. Decision P4-HDN-002: AgentResult Immutability

The AgentResult repository shall expose create/get operations, not semantic
update operations.

After insertion, these values are immutable:

- complete result envelope;
- normalized semantic projection;
- `result_hash`;
- result lineage and reference sets.

Publication retries, acknowledgement, and reconciliation shall update
ResultDelivery or publication records only. A business correction requires a
new execution/result or a future explicit revision contract.

## 5. Decision P4-HDN-003: Canonical Result Hash

P4 shall calculate:

```text
result_hash = "sha256:" + lowercase_hex(
    SHA256(UTF8(canonical_json(result_semantic_projection)))
)
```

The semantic projection shall include:

- `schema_version` and tenant/execution binding;
- agent, project, plan, intent, and source-lineage references;
- status and quality;
- completion-verification and structured-result contract references;
- `structured_result`;
- business, child-result, artifact, evidence, and citation references;
- warnings, conflicts, control summary, and provenance.

The projection shall exclude:

- `result_hash` itself;
- `result_id`, because it is the object identity rather than result semantics;
- `created_at`, because wall-clock allocation is not semantic content;
- ResultDelivery/publication state;
- presentation-only or live-channel state;
- raw private content that is represented by a stable reference and hash.

Canonical JSON rules are:

- UTF-8 encoding;
- object keys sorted lexicographically;
- no insignificant whitespace;
- stable JSON scalar normalization;
- array order preserved;
- no NaN, Infinity, implementation-specific object stringification, or
  non-JSON scalar values.

Result assembly shall be deterministic. Reference arrays that are semantically
sets shall be sorted before the projection is built. STEP 9 shall select an
existing repository canonical-JSON utility when conformant, or define one with
fixed test vectors. It shall not invent a second incompatible hash utility.

The full envelope may have a separate storage-integrity digest in a future
contract. P4 `result_hash` remains the semantic projection hash above.

## 6. Decision P4-HDN-004: Atomic Result Boundary

The following records shall be created in one AE local PostgreSQL transaction:

1. immutable AgentResult;
2. complete required ResultDelivery plan;
3. one deduplicated `PUBLISH_RESULT` RuntimeJob for each pending required
   delivery, with the corresponding `result_delivery_id`.

No network or cross-service call may occur inside this transaction.

If any insert or invariant check fails, the transaction shall roll back all
three record groups. A durable AgentResult without its required delivery plan
is not an admissible P4 state.

Duplicate behavior:

- same execution, result identity, envelope, and hash returns the existing
  aggregate idempotently;
- same identity with different semantic projection fails with a stable
  conflict code;
- duplicate publication scheduling reuses the same dedup key.

## 7. Decision P4-HDN-005: P4 IA Delivery Plan

Every terminal P4 IA AgentResult shall have exactly one:

```text
target_type = WORKSPACE_RESULT
required = true
```

The target reference shall identify the authoritative owner-scoped durable
Workspace/Conversation result destination.

An `ARTIFACT_STORE` delivery is required only when the trusted source/work
contract explicitly requires an artifact. Existing artifact references alone
do not silently create a new required delivery rule.

P4 shall not create `WC_WORK_RESULT`. P4 shall not create optional Email,
Messenger, WA, Metrics, Analytics, or Dashboard deliveries.

The AE migration should add a P4-compatible uniqueness constraint equivalent
to:

```text
at most one WORKSPACE_RESULT per (tenant_id, result_id)
```

Service validation shall additionally prove existence, `required=true`, and
the complete plan. Database uniqueness alone cannot prove exactly-one
existence.

## 8. Decision P4-HDN-006: Minimum Conformant IA Publication

P4 shall implement the bounded publication path needed for IA
`WORKSPACE_RESULT`. It shall not mark a delivery acknowledged from legacy Chat
completion alone.

Every publication attempt shall perform an `AS_OF_NOW` preflight that produces
durable evidence for:

- current OA decision reference;
- tenant and trusted project scope;
- organization scope where applicable;
- data classification;
- recipient/owner visibility;
- resource/workspace visibility;
- correlation and evaluation time.

No check boolean may be set to true unless the corresponding check actually
ran. Browser-supplied tenant, agent, project, or owner values are not
authoritative inputs.

The publisher shall use the Frozen stable publication identity derived from:

```text
result_id + target_type + target_ref + result_hash
```

The delivery may enter `ACKNOWLEDGED` only after the owner-scoped durable
Workspace result can be read back or otherwise authoritatively confirmed at
the target reference. Socket/SSE/browser delivery is not the durable ACK.

If authorization is denied or authoritative durability cannot be proven, the
delivery remains non-acknowledged and canonical AgentExecution success remains
blocked.

## 9. Decision P4-HDN-007: Crash and Retry Safety

A process crash after the atomic result transaction shall leave a durable
pending delivery and a deduplicated `PUBLISH_RESULT` RuntimeJob.

Retry shall:

- preserve PublicationOperationId and idempotency identity;
- perform a new `AS_OF_NOW` preflight;
- read back the same durable workspace target before ACK;
- never regenerate AgentResult;
- never re-enter legacy business/generation execution.

External-target `UNKNOWN_DELIVERY` reconciliation and its append-only outcome
store remain P9 scope. The P4 local workspace publisher shall still fail closed
if it cannot prove whether the durable target exists.

## 10. Decision P4-HDN-008: Completion Guard

The completion service shall evaluate in this order:

1. AgentResult exists and reconstructs successfully;
2. delivery plan is marked complete and passes P4 IA plan validation;
3. required delivery count is greater than zero;
4. exactly one required `WORKSPACE_RESULT` exists;
5. every required delivery is `ACKNOWLEDGED` with acknowledgement time and
   latest preflight reference;
6. AgentExecution transition uses the expected current version.

Only then may the runtime transition through `FINALIZE` to `SUCCEEDED`.

`can_finalize_success([]) == true` from a low-level helper must never be used
as the complete domain decision. The domain guard shall validate plan
completeness before checking acknowledgement states.

## 11. Rollout Behavior

### disabled

- Existing v1.0 behavior only.
- Canonical wrapper is not required for legacy request success.

### shadow

- Canonical admission/result/publication is attempted.
- Wrapper failure does not corrupt or fail a valid legacy request.
- Failure is recorded with safe diagnostics.
- A failed/incomplete canonical execution is never reported as canonical
  `SUCCEEDED`.

### required

- Trusted tenant, active IA, project, owner/workspace context, persistence,
  preflight, durable ACK, and completion guard are mandatory.
- Missing authority or evidence fails deterministically.
- No synthetic agent/project/preflight evidence is permitted.

Transition deployment remains `disabled` by default until P4 acceptance passes.

## 12. Physical Migration Guidance

P4 migrations shall be additive and owned by the AE database.

They may extend the Frozen SQL profile with:

- `schema_version` and `result_envelope_json` on AgentResult persistence;
- a partial unique index for one workspace delivery per result;
- a check or repository invariant requiring workspace delivery to be required;
- indexes needed for pending publication and execution-result lookup.

They shall not:

- modify the files under `docs/frozen/v2.1/`;
- rename or repurpose existing v1.0 tables;
- create cross-service foreign keys;
- store raw generated content in runtime metadata tables.

PostgreSQL DDL is canonical. SQLite may provide a behaviorally equivalent
repository representation for fast regression, with protected PostgreSQL
migration and transaction smoke as the dialect authority.

## 13. Required Test Evidence

P4 implementation shall include tests for:

- complete AgentResult schema reconstruction;
- normalized-column/envelope parity;
- fixed canonical hash vectors;
- immutable result persistence;
- atomic rollback when delivery or job insertion fails;
- duplicate identical result idempotency;
- duplicate conflicting result rejection;
- exactly-one workspace delivery;
- zero-delivery completion rejection;
- non-ACK delivery completion rejection;
- real preflight evidence and fail-closed denial;
- ACK only after durable target confirmation;
- crash/restart continuation from pending publication;
- no legacy generation/business re-execution during publication retry;
- disabled, shadow, and required rollout behavior;
- SQLite behavioral regression and actual PostgreSQL smoke;
- relevant authenticated Chat/RAG Playwright regression.

## 14. Deferred Boundaries

The following remain outside P4:

- WC WorkResult and claim-lineage publication;
- external Email/Messenger/Notification fan-out;
- production external-target `UNKNOWN_DELIVERY` reconciliation;
- append-only external reconciliation outcome persistence;
- WA projection;
- NSL, WRITE, Approval, EOS, and Schedule semantics.

Deferral does not permit fake ACK or false success.

## 15. STEP 8.1 Exit Gate

- [x] Complete AgentResult persistence decision fixed
- [x] Result hash projection fixed
- [x] Result/delivery/publication-job atomicity fixed
- [x] IA required-delivery plan fixed
- [x] Minimum conformant IA publication fixed
- [x] Empty-plan success prohibited
- [x] Crash/retry boundary fixed
- [x] Rollout behavior fixed
- [x] Deferred publication scope explicit
- [x] Frozen product documents unchanged
- [x] Issue and test traceability companion documents required

> STEP 8.1 design is ready to feed STEP 9 source audit and Slice planning.
