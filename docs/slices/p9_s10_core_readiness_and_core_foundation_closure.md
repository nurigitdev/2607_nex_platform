# P9-S10: Core Read APIs, Readiness, and P9.2 Closure

## Scope

P9-S10 makes the local NeX-WA domain independently operable while preserving
the P9 Foundation boundary. It adds no migration and claims no AE/WC source
integration.

Activated routes:

```text
GET /internal/v1/work-evidence/{work_evidence_id}
GET /internal/v1/work-assets/{work_asset_id}
GET /internal/v1/work-assets/{work_asset_id}/evidence
GET /health
GET /ready
```

`/health` and `/ready` use the shared Platform service shell. Readiness checks
the configured WA database and the complete owner-local migration ledger.

Consumer readiness is available without claiming work:

```text
python -m nex_wa.consumer_main --check
```

It verifies migrations plus `service_jobs`, `service_worker_heartbeats`,
`wa_work_evidence`, `wa_work_asset`, and `wa_work_asset_evidence`.

## Authorization

All routes require audience `nex-wa` and `service:call`.

```text
exact WorkAsset       -> work:evidence:read
exact WorkEvidence    -> work:evidence:read + work:evidence:detail:read
asset evidence lineage -> work:evidence:read + work:evidence:detail:read
initial callers       -> nex-ae-api, nex-ag
```

Tenant identity is mandatory in `X-NeX-Tenant-Id`. Repository reads always
bind tenant and record ID, so a valid ID in another tenant returns `404`.
Direct browser tokens and raw source content are outside this boundary.

Lineage ordering is deterministic:

```text
PRIMARY first
SUPPORTING by occurred_at then work_evidence_id
```

## Contracts

P9-S10 adds the first NeX-WA OpenAPI document and machine-readable schemas for:

```text
wa_work_evidence.v1
wa_work_asset.v1
wa_work_asset_evidence_lineage.v1
```

## Actual PostgreSQL Core Acceptance

The protected acceptance used the actual local target:

```text
database = nex_wa_test
role     = nex_wa_user
```

It proved:

```text
all WA migrations current                  = PASS
consumer --check                           = READY
100 identical intake notifications         = one durable Job
two concurrent consumers                    = distinct SKIP LOCKED claims
stale crash recovery                        = fenced and completed by new owner
crash after local domain commit + replay    = idempotent
WorkEvidence count after replay             = 1
WorkAsset count after replay                = 1
binding count after replay                  = 1
protected health/readiness/read APIs        = PASS
post-acceptance database residue            = 0
```

All protected PostgreSQL smokes from P9-S02 through P9-S10 were then rerun
with their guards explicitly enabled: `8 passed`.

## Quality Evidence

```text
NeX-WA Slice Gate       = 159 passed, 8 skipped
statement coverage      = 98.07%
branch coverage         = 95.49%
protected PG smoke set  = 8 passed
contract validation     = 214 schemas / 278 examples / 235 negatives / 10 OpenAPI
Repository Full Gate    = 18,015 passed, 126 skipped
repository statement    = 96.03%
repository branch       = 95.27%
ruff                    = PASS
```

The eight skipped tests in the ordinary Slice Gate are protected PostgreSQL
tests; they were separately enabled and all passed.

The first Full Gate found one stale P8 assertion that fixed the OpenAPI
inventory at nine documents. NeX-WA is the tenth validated OpenAPI asset, so
the assertion now compares the validation result with the independently
calculated repository inventory instead of replacing one hard-coded count
with another. The focused regression and the complete Full Gate then passed.

## P9-CA02 Exit

```text
P9-S01 through P9-S10       = complete
local WA domain             = independently operable
actual PostgreSQL           = PASS
contracts                   = PASS
Repository Full Gate        = PASS
source-owner integration    = not claimed
next Slice                  = P9-S11
```
