# P9-S03: WorkEvidence Persistence, Identity, and Hash

## Scope

P9-S03 introduces the immutable atomic evidence fact owned by NeX-WA:

```text
wa_work_evidence
```

It does not introduce WorkAsset, asset binding, source HTTP adapters, or worker
claim behavior.

## Identity and Hash

`work_evidence_id` is deterministic UUIDv5 over canonical JSON containing:

```text
tenant_id
source_type
source_ref
source_revision_ref
```

The namespace seed is domain-separated with `nex-wa-work-evidence-v1`.

`evidence_hash` uses `nex_runtime.semantic_hashes.semantic_sha256_hash_ref` and
binds the exact SRS semantic projection. `observed_at`, `created_at`, status,
and the hash itself are excluded. Timestamps included in the projection are
normalized to UTC with fixed microsecond precision.

## Persistence Invariants

The table enforces:

```text
primary key        = tenant_id + work_evidence_id
source uniqueness = tenant_id + source_type + source_ref + source_revision_ref
actor type         = HUMAN | AGENT
agent snapshot     = IA | CA | PA | EA | NULL
classification     = INTERNAL | CONFIDENTIAL | RESTRICTED
status             = ACTIVE | SUPERSEDED | INVALIDATED
hash format        = sha256:<64 lowercase hex>
```

Supersession uses a composite self-FK over `(tenant_id, work_evidence_id)`.
This rejects cross-tenant targets at the database boundary. Self-supersession
is rejected in both domain validation and DDL.

No global PRIMARY/SUPPORTING role exists on WorkEvidence. That role remains
owned by the P9-S04 asset-evidence binding.

## Idempotency

```text
same source identity + same source hash      -> existing record reused
same source identity + different source hash -> WA_SOURCE_IDEMPOTENCY_CONFLICT
new source revision                           -> new deterministic identity
```

Concurrent unique-insert winners are re-read and reused. Constraint failures
that cannot resolve to the same source identity fail closed without overwrite.

## Protected PostgreSQL Evidence

Actual `nex_wa_test / nex_wa_user` verification proved:

```text
2603 migration applied/current       = PASS
deterministic create/get              = PASS
exact replay reuse                    = PASS
source-hash conflict                  = PASS
same-tenant supersession              = PASS
source and lifecycle constraints      = PASS
cross-tenant/self guard               = PASS
zero residue after smoke              = 0 rows
```

## Quality Evidence

```text
focused WA regression          = 46 passed, 2 protected skips
actual PostgreSQL smoke        = 1 passed
statement coverage             = 100.00% (floor 96.00%)
branch coverage                = 100.00% (floor 94.00%)
contract validation            = PASS
```

## Exit

```text
immutable WorkEvidence record = PASS
deterministic identity        = PASS
canonical semantic hash      = PASS
idempotency conflict         = PASS
tenant supersession boundary = PASS
next Slice                   = P9-S04
```
