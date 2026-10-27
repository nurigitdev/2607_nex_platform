# P9-S04: WorkAsset and Evidence-Binding Persistence

## Scope

P9-S04 adds the durable NeX-WA materialized work object and its asset-relative
evidence bindings:

```text
wa_work_asset
wa_work_asset_evidence
```

It does not add source adapters, worker claim processing, publication, or
cross-service query APIs.

## Identity and Hash

WorkAsset identity is deterministic and type-specific:

```text
AGENT_EXECUTION_RESULT = tenant_id + agent_execution_id
HUMAN_OWNED_ARTIFACT   = tenant_id + artifact_id + artifact_version_id
```

The semantic hash uses the shared `nex_runtime.semantic_hashes` implementation.
It binds the stable asset projection and bindings sorted by binding role and
WorkEvidence ID. Runtime timestamps, version, and the hash itself are excluded.

## Binding Invariants

`wa_work_asset_evidence` is the sole owner of PRIMARY/SUPPORTING semantics.
An ACTIVE asset must have exactly one PRIMARY binding. Domain validation prevents
zero or multiple PRIMARY bindings, while a partial unique PostgreSQL index also
prevents more than one PRIMARY. Composite foreign keys ensure that both asset and
evidence belong to the same tenant.

The same WorkEvidence may be PRIMARY for one asset and SUPPORTING for another;
the role is intentionally asset-relative.

## Replay and Versioning

```text
same deterministic identity + same semantic hash = existing row reused
same deterministic identity + material change    = version + 1
stale optimistic update                          = WA_ASSET_CONCURRENT_UPDATE
missing/cross-tenant evidence                    = WA_ASSET_EVIDENCE_INVALID
```

Creation, binding replacement, and version updates are committed atomically in
the local WA database transaction.

## Protected PostgreSQL Evidence

Actual `nex_wa_test / nex_wa_user` verification proved:

```text
2604/2605 migrations applied/current = PASS
deterministic create and exact replay = PASS
material binding change/version + 1  = PASS
single PRIMARY and tenant alignment   = PASS
asset/binding readback                = PASS
zero residue after smoke              = 0 rows
```

## Quality Evidence

```text
focused WA regression          = 68 passed, 3 protected skips
actual PostgreSQL smoke        = 1 passed
statement coverage             = 99.66% (floor 96.00%)
branch coverage                = 97.96% (floor 94.00%)
contract validation            = PASS
```

## Exit

```text
durable WorkAsset                 = PASS
asset-relative evidence binding  = PASS
tenant-aligned composite FK      = PASS
deterministic replay/versioning  = PASS
next Slice                       = P9-S05
```
