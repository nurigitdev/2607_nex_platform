# P9-S01: NeX-WA Service Identity and Repository Skeleton

## Scope

P9-S01 establishes NeX-WA as a first-class Platform service without adding
WorkEvidence, WorkAsset, intake, or evidence-processing behavior.

Canonical runtime identity:

```text
service_id                 = nex-wa
package                    = nex_wa
default endpoint           = http://127.0.0.1:8108
endpoint environment       = NEX_WA_BASE_URL
runtime database           = NEX_WA_DATABASE_URL
test database              = NEX_WA_TEST_DATABASE_URL
runtime artifact           = nex-wa-runtime
API process                = nex-wa-api
consumer process           = nex-wa-evidence-consumer
consumer worker type       = wa.evidence_consumer
```

The consumer is an idle process shell in this Slice. It imports and reports
package readiness but cannot claim or process domain work before P9-S08.

The owner-local migration stream is frozen before P9-S02 as
`2600` baseline, `2601` common JobQueue, `2602` heartbeat, `2603`
WorkEvidence, `2604` WorkAsset, and `2605` asset-evidence binding.

## Registry Reconciliation

The current first-class backend set is frozen as:

```text
nex-oa
nex-ag
nex-ae-api
nex-cx
nex-mo
nex-wc
nex-eos
nex-wa
```

The same set is enforced across service identity, endpoint, PostgreSQL test
target, worker heartbeat, service log, mock token, signed token, and OA
service-principal audience registries. This also reconciles WC/EOS omissions
left in older five-service topology and PostgreSQL target catalogs.

`SERVICE_RUNTIME_OPERATION_SPECS` intentionally excludes NeX-WA until its
job-control and operational read APIs activate in their owning later slices.

## Trust Boundary

NeX-WA accepts service tokens only for audience `nex-wa`. The OA in-memory and
production token allowlists, signed verifier, and PostgreSQL constraints now
admit that audience.

Migration `2517_oa_service_principal_wa` changes only existing OA CHECK
constraints. It creates no table, credential, principal, or token. Outbound
WA trust grants remain owned by P9 source-integration/deployment slices.

## Verification

Focused shared-registry regression:

```text
218 passed
0 failed
```

P9-S01 NeX-WA Slice Gate:

```text
15 passed
statement coverage = 100.00% (floor 96.00%)
branch coverage    = 100.00% (floor 94.00%)
```

Actual `nex_oa_test` protected verification:

```text
2517_oa_service_principal_wa applied
oa_service_principals_service_id_check includes nex-wa
oa_token_revocations_audience_check includes nex-wa
```

The previously prepared `nex_wa_dev` and `nex_wa_test` identities were also
confirmed before this Slice as owned by `nex_wa_user`, with PostgreSQL 16.9
connectivity and public-schema usage/create permissions.

## Exit

```text
service identity uniqueness       = PASS
port and endpoint contract        = PASS
registry completeness             = PASS
OA token audience admission       = PASS
runtime/process topology          = PASS
deployment artifact ownership     = PASS
domain tables introduced          = NO
domain behavior activated         = NO
P9-S01 Slice Gate                 = PASS
next Slice                        = P9-S02
```
