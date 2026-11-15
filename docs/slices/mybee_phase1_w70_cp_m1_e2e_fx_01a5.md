# CP-M1-E2E-FX-01A.5: Installed M1 Runtime Promotion

## Status

- Slice: `CP-M1-E2E-FX-01A.5`
- Status: `CLOSED`
- Database migration: none
- Remote provider: not required
- Active runtime profile: `VERIFIED_PRODUCT_RELEASE`
- Bounded rollback: `GOLDEN_A_ROLLBACK` until `CP-M1-GA-RET-02`

## Decision

The canonical AE Agent Runtime worker now selects the immutable signed M1
release through its activation lock, admission lock, Product Capability
Registry, and operation registry. The active release contains exactly:

- `PROJECT.WORK_CODE_SET.GET` as the D12 NSL READ operation;
- `FINANCE.VOUCHER.APPROVE_AND_POST` as the D04 governed WRITE operation.

The installed runtime executes D12 through the admitted NSL package and keeps
private NSL imports behind the shared `nex_runtime` adapter boundary. D04
reuses the durable approval, idempotency, controlled WRITE, EOS verification,
and reconciliation ports already admitted by P8 and W70.

Golden A is not an active product selector. Its historical bundle and authority
profile remain packaged only for the bounded rollback receipt until
`CP-M1-GA-RET-02` removes the active rollback binding.

## Installed Composition

- the canonical Compose worker selects `VERIFIED_PRODUCT_RELEASE` explicitly;
- OCI packaging includes the exact signed NSP, public key, D12/D04 source,
  Tool catalog, EOS contracts and schemas, WorkCode catalog, registry, and
  admission/activation locks;
- the OCI build fails closed if the reconstructed M1 admission differs from
  the immutable lock;
- the image runs as `65532:65532` and performs no registry push;
- the image evidence distinguishes the active verified release from the
  bounded Golden A rollback bundle;
- Compose retains the Golden A retirement projection so new Golden A
  selection remains denied during the transition.

## Fail-Closed Coverage

Regression covers unknown capability, Skill-binding drift, missing WRITE or
continuation handlers, invalid READ cardinality, OA scope denial, malformed or
unresolved compiled inputs, ambiguous Project context, malformed operation
registrations, activation-lock drift, rollback receipt drift, and private NSL
module leakage into AE runtime code.

## Protected Evidence

### Actual PostgreSQL

```text
database                         = nex_ae_test
role                             = nex_ae_user
migration state                  = current
signed D12/D04 artifact count    = 2
exact artifact replay            = PASS
post-gate tenant residue         = 0
```

Evidence is written to
`reports/smoke/w70-cp-m1-e2e-fx-01a5-postgres-gate.json` with the database
password redacted.

### Actual OCI

```text
image                            = nex-platform-canonical/nex-ae-runtime:w70-cp-m1-01a5
actual build                     = PASS
runtime user                     = 65532:65532
build-time M1 admission          = PASS
registry push                    = false
active runtime profile           = VERIFIED_PRODUCT_RELEASE
bounded rollback role            = BOUNDED_ROLLBACK_UNTIL_CP_M1_GA_RET_02
```

The immutable image ID, source-context digest, lock digest, and release
identities are recorded in
`reports/deployment/w70-cp-m1-e2e-fx-01a5-ae-runtime-image.json`.

## Regression

```text
focused installed/compatibility regression = PASS
AE Slice Gate                              = 6,009 passed / 46 protected skips
AE statement coverage                      = 96.15%
AE branch coverage                         = 94.11%
contract validation                        = PASS
Golden Journey transition audit            = PASS
demo/product dependency audit              = PASS
Golden A retirement artifact check         = PASS
Golden A no-new-selection Gate              = PASS
```

## Closure

`CP-M1-E2E-FX-01A` is closed through `.1` to `.5`. This Slice proves the
installed composition and protected persistence boundary; it does not replace
the later public M1 journey acceptance. The next boundary is
`CP-M1-GA-RET-02: Golden A Active Binding Removal and Historical Quarantine`,
followed by the original `CP-M1-E2E-FX-01` public Golden E2E.
