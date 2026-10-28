# GB2-CA00-S15: RustFS / S3 Object-Storage Provisioning and Readiness

## Scope

S15 moves private bucket and owner-IAM preparation out of Golden
Journey-specific code into one deployment-owned operation. It reuses the
existing S3-compatible runtime client, private bucket lifecycle bootstrap, and
RustFS IAM client. It adds no database migration, RustFS-specific application
SDK, payload table, WA byte storage, or second object-store implementation.

## Canonical Ownership

`nex_runtime.object_storage_provisioning` composes the existing owners:

```text
bootstrap_private_bucket
-> RustfsAdminClient.provision_bucket_owner
-> owner head_bucket
-> cross-owner head_bucket denied
-> S13 dependency readiness
```

The initial owner inventory is source-backed by `OBJECT_STORAGE_OWNERS` and is
strictly limited to:

```text
nex-ae-api -> nex-ae-private -> object-storage:ae
nex-cx     -> nex-cx-private -> object-storage:cx
```

NeX-WA remains metadata-only and receives no byte-storage bucket in this
Slice. Owner ordering is canonicalized to AE then CX so evidence and readiness
hashes are independent of caller ordering.

## Readiness Contract

An owner is ready only after all of the following complete:

```text
configuration/credential admission
bucket lifecycle provisioning and readback
owner IAM/policy provisioning
owner-scoped head_bucket succeeds
the same credential receives HTTP 403 for the other owner's bucket
```

Successful observations map to the S13 contract with `configured`,
`provisioned`, `reachable`, and `authorized` all true. Unknown transport
failures, permissive cross-owner access, malformed receipts, missing clients,
credential coverage drift, and source inventory drift fail closed with
sanitized errors.

Credential fields are excluded from dataclass representations. Public evidence
contains owner identity, hashed bucket reference, lifecycle/IAM posture, and
readiness hashes, but no credentials, endpoints, object keys, or payloads.

## Demo And Protected Runner Rebind

P8-DEMO S10 `_provision_demo_object_storage()` now constructs clients and then
delegates bucket, IAM, access, and isolation logic to the canonical operation.
The S146 protected runner uses the same operation and calls only runtime
readiness verification after RustFS restart. Its former local cross-bucket
authorization implementation was removed.

## Protected Acceptance

The final run used actual local PostgreSQL, Docker, OpenBao, Traefik, and
digest-pinned RustFS:

```text
test PostgreSQL migration services   = 5
metadata-only PostgreSQL probes       = AE / CX PASS
private buckets / owner identities    = 2 / 2
versioning / SSE-S3 / lifecycle       = PASS / PASS / PASS
managed TLS / non-root / volume       = PASS / PASS / PASS
AE -> CX / CX -> AE access            = DENIED / DENIED
CX source + Markdown round-trip       = PASS / PASS
AE generated-response round-trip      = PASS
RustFS process restart recovery       = PASS
final S13 dependency readiness        = AE READY / CX READY
cleaned object versions / buckets     = 9 / 2
named volume removed                  = true
raw secret/private payload evidence   = absent
```

Ignored local evidence is available at:

```text
reports/deployment/s146-object-storage-acceptance.json
reports/quality/gb2-ca00-s15-platform.coverage.json
```

## Verification

```text
focused S15/Demo/S146 tests           = 39 passed
object-storage surrounding regression = 170 passed
Platform Slice Gate                   = 423 passed / 7 skipped
Slice statement / branch              = 100.00% / 100.00%
contract validation                   = 227 / 291 / 245 / 10
Golden Journey transition audit       = PASS
actual PostgreSQL/RustFS smoke         = PASS
ruff / diff check                     = PASS
database migration added              = NONE
remote model provider                 = NOT REQUIRED
```

The seven Slice Gate skips are existing protected opt-in PostgreSQL tests. S15
executed its PostgreSQL/RustFS protected acceptance separately. No production
container bootstrap was modified, so a risk-escalated Checkpoint Gate was not
triggered.

## Exit

```text
object-storage provisioning owner     = DEPLOYMENT
application runtime provisioning      = NONE
AE/CX admitted storage readiness       = ACTIVE
cross-owner isolation                  = FAIL-CLOSED
WA byte storage                        = NOT ADDED
restart recovery                       = PASS
next slice                             = GB2-CA00-S16
```
