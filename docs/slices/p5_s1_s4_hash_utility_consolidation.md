# P5-S1..S4 Hash Utility Consolidation

## Scope

- Audit the P5-S1 through P5-S4 production paths for duplicate SHA-256 and
  canonical JSON implementations.
- Preserve every existing persisted representation and contract.
- Keep the change independent of remote model providers.

## Findings

- P5 semantic objects already used the shared `semantic_sha256_hash_ref`
  entrypoint.
- WorkIntent, AgentContext, CapabilitySnapshot, AgentPlan, and
  PlanValidationResult each duplicated the same canonical JSON serializer.
- Prompt Registry text digests and IntentDecision digests used separate direct
  `hashlib.sha256` implementations.
- The dual representation is intentional and remains unchanged:

```text
legacy and *_sha256 fields = 64 lowercase hexadecimal characters
P5 semantic *_hash fields  = sha256:<64 lowercase hexadecimal characters>
```

## Decision

- `nex_runtime.semantic_hashes` is the single P5 owner of:
  - UTF-8 canonical JSON with sorted keys, compact separators,
    `ensure_ascii=False`, and `allow_nan=False`;
  - SHA-256 calculation for text;
  - bare digest validation;
  - semantic hash-reference validation and lossless conversion.
- `semantic_sha256_hash_ref` composes the shared canonicalizer and text digest
  primitive instead of calculating SHA-256 independently.
- The existing `nex_runtime.prompts.sha256_text` import path remains a
  compatibility alias to the shared primitive. Existing callers do not need a
  flag day migration.
- Converting a bare digest to or from `sha256:<digest>` never hashes the digest
  again.

## Refactoring Result

- Removed five duplicate P5 canonical JSON functions.
- Removed direct SHA-256 calculation from the Prompt Registry implementation
  and IntentDecision policy.
- Routed Prompt Registry persistence validation directly through the shared
  digest primitive.
- Added regression assertions proving that bare and semantic hashes use the
  same canonical bytes and SHA-256 primitive, including Korean text.

## Verification

- Focused P5 and Prompt Registry regression: `277 passed`.
- Actual PostgreSQL smoke against `nex_ae_user@nex_ae_test`: `11/11` checks,
  `35` migrations current, one validation row persisted and verified, zero
  compile rows, and zero cleanup residue.
- AE Slice Gate: `3338 passed`, `5` protected opt-in smoke tests skipped.
- Statement coverage: `98.52%` against the `95%` gate.
- Branch coverage: `96.63%` against the `94%` gate.
- Contract validation: `174` schemas, `236` examples, `204` negative examples,
  and `7` OpenAPI documents passed.

## Boundary

This correction centralizes the P5-S1 through P5-S4 planning path. Older
service-local hash helpers outside this path were inventoried but were not
mechanically changed because they cover binary artifacts, authentication,
deployment provenance, or legacy compatibility contracts with different byte
projections. They should be migrated only under their owning requirement and
with preserved test vectors.
