# P9-S05: WA Local Unit of Work and Semantic Idempotency

## Scope

P9-S05 makes normalized WorkEvidence, WorkAsset, and asset-evidence bindings one
restart-safe NeX-WA local semantic unit. It does not add source HTTP adapters,
worker claim/settlement behavior, publication, or cross-service read APIs.

No database migration is added. The Slice reuses:

```text
wa_work_evidence
wa_work_asset
wa_work_asset_evidence
```

## Transaction Boundary

`WaEvidenceAdmissionService.admit_normalized_evidence()` owns one shared
SQLAlchemy unit of work:

```text
validate tenant and evidence-binding lineage
create/reuse WorkEvidence
create/update WorkAsset
create/reuse asset-evidence binding
commit once
```

The Evidence and Asset repositories expose caller-owned transaction methods;
their existing standalone methods retain their original commit/rollback
behavior. Job settlement remains outside this transaction and may run only
after the local commit succeeds.

## Replay and Concurrency

```text
same source identity + same source hash = reuse
same source identity + different hash   = WA_SOURCE_IDEMPOTENCY_CONFLICT
asset mutation                          = version + 1
concurrent evidence/asset race          = bounded retry
retry exhaustion                        = typed 409 conflict
database failure                        = redacted typed 503
```

A crash after commit is recovered by exact replay without duplicate Evidence,
Asset, binding, or version increments. Evidence creation is rolled back when
asset validation, required evidence, or one-PRIMARY enforcement fails.

## Protected PostgreSQL Evidence

Actual `nex_wa_test / nex_wa_user` verification proved:

```text
database and role identity              = PASS
migrations current through 2605         = PASS
concurrent exact Evidence admission     = PASS
concurrent same-Asset creation          = PASS
concurrent supporting-binding expansion = PASS
stable versions                         = 1 then 2
durable row counts                      = Evidence 2 / Asset 1 / Binding 2
post-smoke zero residue                 = Evidence 0 / Asset 0 / Binding 0
```

## Quality Evidence

```text
focused P9-S01..S05 regression = 77 passed
actual PostgreSQL smoke        = 1 passed
P9-S05 Slice Gate              = 78 passed, 3 skipped
Slice statement coverage       = 99.55%
Slice branch coverage          = 98.25%
admission statement/branch     = 100.00% / 100.00%
Checkpoint Gate #1             = 17,215 passed, 120 skipped
Checkpoint statement coverage  = 98.26%
Checkpoint branch coverage     = 96.72%
contract validation            = PASS
```

## Exit

```text
local atomic UoW                 = PASS
semantic replay                  = PASS
crash-after-commit recovery      = PASS
bounded concurrency retry        = PASS
one-PRIMARY rollback             = PASS
actual PostgreSQL concurrency    = PASS
P9 Checkpoint Gate #1            = PASS
next Slice                       = P9-S06
```
