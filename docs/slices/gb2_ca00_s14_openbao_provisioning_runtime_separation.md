# GB2-CA00-S14: OpenBao Provisioning / Runtime Resolution Separation

## Scope

S14 makes the existing OpenBao deployment preparation reusable outside the P8
Demo runner. It preserves the existing runtime secret-consumption boundary and
adds no database migration, second resolver, business-runtime provisioning
path, or secret persistence mechanism.

## Canonical Boundary

`nex_runtime.openbao_provisioning` now owns the deployment-side composition:

```text
initialize and unseal
-> configure KV, AppRole, owner policies, PKI, and credential files
-> optionally configure S144 Transit and federation trust
-> emit provisioned but not-yet-authorized readiness
```

The existing `OpenBaoSecretResolver` remains the only runtime resolution
implementation. `production_container_bootstrap` remains the owner-process
consumer and was not changed by this Slice.

```text
deployment/bootstrap provisions
container bootstrap resolves owner secrets
business runtime never provisions OpenBao
```

Provisioning alone emits `authorized=false` and therefore `ready=false` under
the S13 readiness contract. Readiness becomes true only after every declared
owner authenticates independently, resolves a scoped secret, validates the
returned metadata, and successfully revokes its runtime token.

## Restart And Evidence Rules

The canonical adapter retains root and unseal custody only in an operator-local
session whose fields are excluded from `repr` and public projections. Restart
reactivation uses that private session to unseal the existing Raft node and
wait for the active leader. Public evidence contains only bounded status,
counts, attempts, readiness booleans, hashes, and redaction declarations.

```text
missing owner environment       -> reject
invalid namespace/version       -> reject
resolver/authentication failure -> sanitized fail-closed error
metadata mismatch               -> sanitized fail-closed error
token revoke failure            -> sanitized fail-closed error
uninitialized restart target    -> reject
restart never active            -> reject
```

## P8-DEMO Rebind

`run_p8_demo_trust_admission.py` is now a consumer of the canonical adapter for
provisioning, owner resolution, and restart reactivation. Its existing secret
rotation and cross-owner denial checks remain intact. A neutral semantic
calibration value is supplied only for Compose interpolation because this
OpenBao-only runner does not start the AE runtime.

## Protected Acceptance

The isolated P8 Demo Compose project executed against the actual local Docker
engine and digest-pinned OpenBao image:

```text
OpenBao storage                    = integrated-raft
provisioned owners / secrets       = 7 / 31
initial owner resolutions          = 7
actual OpenBao process restart     = PASS
restart reactivation attempt       = 3
rotated owner resolutions          = 7
secret generations verified        = 1 / 2
cross-owner access denied          = true
final S13 dependency readiness     = READY
raw custody/secret/token evidence  = absent
runtime/volume residue retained    = false
```

The ignored local evidence is recorded at:

```text
reports/deployment/gb2-ca00-s14-openbao-protected.json
reports/quality/gb2-ca00-s14-platform.coverage.json
```

## Verification

```text
focused S14 + P8 trust tests       = 54 passed
related S13/S14/S143/S144/runtime  = 145 passed
Platform Slice Gate                = 435 passed / 7 skipped
Slice statement / branch           = 100.00% / 97.92%
contract validation                = 227 / 291 / 245 / 10
Golden Journey transition audit    = PASS
ruff / diff check                  = PASS
database migration                 = NONE
remote model provider              = NOT REQUIRED
```

The seven Slice Gate skips are existing protected opt-in PostgreSQL tests. The
S14 OpenBao protected acceptance was executed separately and passed. The plan's
risk-escalated Checkpoint condition was not triggered because
`production_container_bootstrap` was not modified.

## Exit

```text
canonical OpenBao provisioning     = ACTIVE
existing runtime resolver          = PRESERVED
provisioned != runtime ready        = ENFORCED
restart-safe reactivation           = PASS
P8-DEMO direct provisioning owner  = REMOVED
raw secret evidence                 = NONE
next slice                          = GB2-CA00-S15
```
