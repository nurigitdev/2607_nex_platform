# P4 Result Persistence and Publication Design Baseline v1.1

**Status:** P4 IMPLEMENTATION BASELINE
**Supersedes:** `P4_Result_Persistence_and_Publication_Design_Hardening_FROZEN_v1.0.md`

## 1. Boundary

P4 implements:

```text
AgentResult
+ one required WORKSPACE_RESULT ResultDelivery in PENDING state
```

P4 defers:

```text
publication preflight
PUBLISH_RESULT execution
ACK
UNKNOWN_DELIVERY reconciliation
AgentExecution SUCCEEDED
```

## 2. Invariants

```text
AgentResult != GeneratedResponse
AgentResult != ResultDelivery
legacy Chat COMPLETED != AgentExecution SUCCEEDED
```

P4 SHALL NOT fake publication success.

## 3. AgentResult Persistence

Persist the complete schema-valid AgentResult envelope.

Recommended row includes:

```text
schema_version
tenant_id
result_id
agent_execution_id
agent_type
status
quality
structured_result_json
result_envelope_json
result_hash
created_at
```

plus applicable normalized lineage fields.

The complete semantic envelope and `result_hash` are immutable.

Raw prompt/generated body/raw evidence are not copied when stable private references exist.

P4 creates at most one canonical AgentResult per AgentExecution. Persistence
SHALL enforce:

```text
UNIQUE (tenant_id, agent_execution_id)
```

This is stricter than the Frozen seed's redundant
`(tenant_id, agent_execution_id, result_id)` uniqueness and closes duplicate
result races without changing the AgentResult wire contract.

## 4. result_hash

Use:

```text
"sha256:" + sha256(canonical_json(result_semantic_projection))
```

Exclude:

- result_hash itself
- result_id
- created_at
- publication state
- raw private content represented by stable ref/hash

Sort semantically set-like reference arrays before hashing.

Use fixed test vectors.

## 5. Required Delivery Plan

Every terminal IA AgentResult SHALL atomically create exactly one:

```text
target_type = WORKSPACE_RESULT
required = true
state = PENDING
```

No WC WorkResult and no optional fan-out in P4.

For the P4 IA path:

```text
target_ref = authoritative workspace_id
```

Conversation identity remains AgentExecution/AgentResult lineage and is not
encoded as a fake Project or a second delivery target.

Even while state is PENDING and no `PUBLISH_RESULT` job exists, the delivery
SHALL contain the Frozen-required stable identities:

```text
publication_operation_id
idempotency_key_ref
```

They are derived once from
`result_id + target_type + target_ref + result_hash` using the Frozen
publication identity algorithm. The later publication phase reuses these
values and MUST NOT mint replacements.

## 6. Atomicity

P4 SHALL persist in one AE-local transaction:

1. immutable AgentResult;
2. complete P4 required ResultDelivery plan.

P4 does NOT create `PUBLISH_RESULT` jobs in this phase because publication execution/ACK is deferred.

Later publication phase SHALL enqueue publication jobs from durable pending deliveries without regenerating AgentResult.

## 7. Completion Guard

P4 MUST reject transition to AgentExecution `SUCCEEDED`.

After result creation the execution remains in the exact Frozen pre-terminal publication state/phase, expected to be:

```text
state = RUNNING
phase = RESULT_PUBLISH
```

unless the Frozen runtime document defines a more precise equivalent.

Legacy Chat completion remains independently user-visible.

## 8. Idempotency

- same execution/result identity/semantic projection → existing aggregate;
- same identity + different semantic projection → stable conflict;
- duplicate result creation cannot create a second required workspace delivery.

## 9. Tests

Required:

- complete AgentResult round-trip;
- normalized/envelope parity;
- fixed hash vectors;
- immutable result;
- result + delivery atomic rollback;
- duplicate identical idempotency;
- semantic conflict rejection;
- exactly one required WORKSPACE_RESULT;
- PENDING never treated as ACK;
- AgentExecution SUCCEEDED rejected;
- no generation replay during duplicate result creation.

## 10. Deferred Publication

Later phase adds:

```text
AS_OF_NOW preflight
PublicationOperationId
PUBLISH_RESULT RuntimeJob
durable target confirmation
ACKNOWLEDGED
publication retry/reconciliation
AgentExecution FINALIZE → SUCCEEDED
```

P4's durable PENDING delivery is the handoff point.
