# P5 LLM Prompt Template Registry & Governance Design v1.1

**Status:** P5-CA01A COMMON LLM CONTROL-PLANE BASELINE

**Supersedes:** v1.0

## 1. Core principle

```text
Source code
= bootstrap seed / schema / renderer / safety logic

RDBMS Prompt Registry
= operational Prompt Template SoR

Agent semantic artifact
= captured exact version/hash provenance
```

## 2. Existing AE Registry reuse

P5 reuses:

```text
ae_prompt_templates
ae_prompt_template_versions
ae_prompt_bindings
ae_prompt_render_events
SqlAlchemyAePromptRegistryStore
```

No second registry is created.

## 3. Version immutability

PromptTemplateVersion is immutable.

```text
same version + same content/hash
→ idempotent existing record

same version + different content/hash
→ VERSION_CONTENT_CONFLICT
```

The existing mutable `ON CONFLICT ... DO UPDATE content` semantics must be replaced in P5-S1 repository behavior.

## 4. Binding as deployment pointer

`binding_key` points to one exact version.

No implicit `latest`.

Runtime resolution:

```text
binding_key
→ exact prompt_template_version_id
→ content_sha256
→ rendered prompt digest
→ model profile/ref
→ output digest
```

## 5. CA01A atomic binding change

Binding pointer mutation and durable history are one transaction.

Minimum history record:

```text
binding_change_id
binding_key
old_prompt_template_version_id
new_prompt_template_version_id
changed_by
reason
correlation_id
changed_at
```

Required transaction semantics:

```text
BEGIN
SELECT current binding FOR UPDATE
validate expected-current / target version
INSERT history
UPDATE current binding pointer
COMMIT
```

If either DML operation fails, the entire transaction rolls back.

Concurrent changes must use row locking or compare-and-set expected-current semantics.

Switching to the already-current version is an idempotent no-op.

## 6. Execution snapshot isolation

Once an LLM-dependent stage has resolved a binding, it captures exact:

- binding ID/key;
- template version ID/version;
- bare `content_sha256`;
- bare rendered prompt digest compatible with existing Prompt Registry;
- model profile/ref;
- input context semantic hash;
- output bare digest/hash as appropriate.

Later binding changes do not alter the in-flight WorkIntent/AgentPlan/AgentResult provenance.

Retry uses the captured exact version unless a new semantic plan/revision explicitly chooses a new prompt version.

## 7. Hash interoperability

Prompt Registry database digest fields remain bare lowercase 64-hex SHA-256.

P5 semantic object hashes use `sha256:<hex>`.

Conversion is representation-only via shared utility; no double hashing.

## 8. LLM authority boundary

```text
Prompt Template
→ LLM candidate
→ schema validation
→ deterministic policy/validation
→ deterministic compiler
→ execution
```

LLM output never becomes authority for tenant, identity, Project, capability version, approval or WRITE.

## 9. P5 prompt purposes

Registry supports:

```text
intent_resolution
context_candidate_extraction
plan_builder
clarification
result_synthesis
```

Optional LLM Intent/Dynamic Planner remain disabled by default and are not required for P5 closure.

## 10. Trust boundary

System/developer prompt segments are trusted control text.

User prompts, retrieved evidence and model-generated candidates are untrusted data and must remain structurally separated.

## 11. P5-S1 tests

- immutable version same-content idempotency;
- changed-content same-version rejection;
- atomic binding history+pointer success;
- fault between history/pointer rolls back both;
- concurrent expected-current conflict;
- no duplicate history on idempotent same-current request;
- in-flight captured version unaffected by later binding rollback/switch;
- bare/prefixed hash conversion round trip.
