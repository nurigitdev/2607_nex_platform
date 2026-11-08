# GB2-CA00-S17A Product Controlled WRITE Runtime Composition Closure

## Status

```text
Slice                               = GB2-CA00-S17A
Status                              = CLOSED
Canonical owner                     = NeX-AE
Database migration                  = NONE
Business fixture runtime use        = FORBIDDEN
Business fixture allowed use        = PRE-REQUEST DATABASE SEED ONLY
Next Slice                          = GB2-CA00-S18
```

## Goal

Replace the installed AE worker's Demo-owned controlled WRITE composition with
the canonical product runtime. The active worker must execute admitted
`LOCAL_SKILL` work through Product Capability Registry and current service or
PostgreSQL authorities, without reading a Golden Journey business fixture.

## Product Runtime Composition

The canonical process remains:

```text
nex_ae_api.agent_runtime_process --profile staging_live
```

The `staging_live` and `production` profiles compose these executor kinds:

```text
DETERMINISTIC_AGGREGATE
DETERMINISTIC_REPORT
LOCAL_SKILL
P4_CHAT_RAG_COMPATIBILITY
```

`LOCAL_SKILL` uses the admitted product NSL bundle and the controlled WRITE
ports already implemented by P6-P8. The historical `demo_runtime` and P8
controlled-skill modules remain compatibility and regression surfaces only;
they are not active deployment entrypoints.

## Authoritative Data Boundary

Runtime business values are resolved from these authorities:

```text
Product Capability Registry = capability, Skill artifact, bundle identity
AE PostgreSQL               = WorkIntent, AgentContext, attachment manifest
OA                          = current principal and authorization state
WC                          = approval request, decision, and resume evidence
EOS                         = Project, Account, controlled WRITE, verification
```

The product worker does not load the Golden A authority profile. Project code,
amount, date, currency, voucher type, and account codes originate from the
persisted WorkIntent. EOS resolves the caller-visible Project and the effective
Account records from PostgreSQL before the NSL binding is built. Attachment
input is accepted only from a locked AE PostgreSQL manifest whose hash matches
the WorkIntent binding.

## Fixture Boundary

The product NSL bundle excludes `fixtures/success.json` and the product image
does not copy a fixture directory. Business fixtures may be used only before a
request to seed test or Demo databases. A worker request cannot load, infer,
or override business input from a fixture.

The executable deployment audit fails when an active AE deployment path uses:

```text
nex_ae_api.demo_runtime
NEX_AE_DEMO_*
fixture content in the product NSL bundle or OCI context
protected_input as product business input
Golden A authority profile as worker business input
```

## Deployment

The Compose worker command is bound to the canonical process and product
profile. The OCI context packages the admitted wheel, exact seven-file Skill
artifact, product bundle manifest, Product Capability Registry, policy
profile, and locks. Runtime NSL state is written to the dedicated AE runtime
volume. No registry push is performed by the local builder.

## EOS Read Authority

EOS now exposes a service-token-protected, tenant-scoped Account read endpoint
for product execution binding. It reuses the existing account repository and
fails closed for unavailable storage, missing accounts, tenant mismatch, and
invalid service authority. No schema change was required.

## Verification

```text
focused product/runtime regression      = 127 passed
AE Slice Gate                           = 5,711 passed / 45 skipped
AE statement / branch coverage          = 96.76% / 95.02%
EOS Slice Gate                          = 748 passed / 22 skipped
EOS statement / branch coverage         = 95.65% / 94.04%
EOS Account API statement / branch      = 100.00% / 100.00%
deployment residue audit                = PASS
product OCI bundle dry-run              = READY (7 Skill files, no fixture)
actual PostgreSQL database              = nex_ae_test / nex_ae_user
actual PostgreSQL migrations            = 61 / 61 current
actual product worker readiness         = READY
actual product executor profile         = LOCAL_SKILL + existing executors
actual EOS PostgreSQL account authority = PASS (nex_eos_test, TRAVEL ACTIVE)
database migration                      = NONE
```

The PostgreSQL readiness run used the canonical `staging_live` process. It
connected directly to `nex_ae_test`, inspected current migrations and runtime
tables, composed the Product Capability Registry and admitted NSL package, and
made no OA or EOS network request during readiness.

## Exit

```text
active AE worker uses demo_runtime       = NO
active AE worker reads business fixture  = NO
product capability source                = PRODUCT CAPABILITY REGISTRY
business state source                    = AE/OA/WC/EOS AUTHORITIES
Compose entrypoint                       = nex_ae_api.agent_runtime_process
deployment residue guard                 = INSTALLED
next slice                               = GB2-CA00-S18
```
