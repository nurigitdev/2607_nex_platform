# P6-CA01 READ Transition Contracts

**Status:** SOURCE-BACKED CONTRACT BASELINE
**Scope:** P6 NSL READ integration only

These schemas project the Frozen Agent v2.1 to NSL v0.2 integration contract
onto the current NSL v0.1 backend. They are transition contracts, not changes
to the Frozen baseline.

## Contract Set

| Contract | Purpose |
|---|---|
| `p6-skill-execution-request-v1.schema.json` | Canonical AE-facing READ request and stable identity envelope |
| `p6-verified-skill-artifact-v1.schema.json` | Exact Skill/package/trust projection produced by the AE artifact gateway |
| `p6-nsl-result-summary-v1.schema.json` | Bounded deterministic result/evidence projection; no raw audit copy |
| `p6-nsl-step-execution-binding-v1.schema.json` | Durable pre-invocation identity and request/result lineage |
| `p6-step-result-v1.2.schema.json` | Current StepResult writer contract with LOCAL_SKILL READ BusinessOperationId |
| `p6-context-projection-v1.schema.json` | Bounded AgentContext-to-NSL projection and verified security context |

`examples/` contains one coherent Golden READ lineage and its source-backed
fixture manifest.

## Hash Rules

All transition semantic hashes use the repository shared canonical hash
utility:

```text
UTF-8 JSON
+ sorted keys
+ compact separators
+ no NaN/Infinity
-> SHA-256
-> sha256:<lowercase hex>
```

The projections are:

| Hash | Projection |
|---|---|
| `projection_hash` | ContextProjection excluding `projection_hash` |
| trust `evidence_hash` | trust evidence excluding `evidence_hash` |
| `artifact_hash` | VerifiedSkillArtifact excluding `artifact_hash` |
| binding `request_hash` | complete SkillExecutionRequest |
| binding `result_summary_hash` | complete NSLResultSummary |
| StepResult `result_hash` | StepResult excluding identity/timestamps/result hash, preserving the P5 semantic-hash rule |

`NSLResultSummary.result_hash` is different: it is the SHA-256 hash of the
canonical NSL v0.1 `RuntimeResultEnvelope` bytes kept behind `result_ref`.

## Compatibility

- Readers introduced in P6 accept historical P5 StepResult `1.1` and current
  P6 StepResult `1.2` through explicit version dispatch.
- P6 writers emit `1.2` only for the new implementation path.
- Historical `1.1` records are not mutated or backfilled.
- For `LOCAL_SKILL`, `business_operation_id` is a UUID and
  `operation_fingerprint` is null.
- For non-NSL executors, both values remain null.

## Security Boundary

The request never contains the whole AgentContext. The context projection is
bounded to declared runtime paths, explicit resources, a verified principal,
authority metadata, and data policy. Implementations must recursively reject
credential-bearing keys or values even where JSON Schema permits a typed value.

The verified artifact persists bounded trust metadata plus evidence refs/hashes.
Signature bytes and raw package verification journals remain in the NSL/package
evidence boundary.
