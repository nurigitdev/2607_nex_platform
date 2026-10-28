# GB2-CA00-S13: Dependency Readiness Contract Foundation

## Scope

S13 introduces the shared, secret-free dependency readiness vocabulary used by
later OpenBao, object-storage, and model-provider activation slices. It adds no
database migration, network probe, provisioning command, persistence engine, or
Golden Journey transition.

## Ownership Boundary

The shared layer consumes owner-produced signals only:

```text
OpenBao deployment/bootstrap and runtime resolution
Object-storage lifecycle and authorization
NeX-MO ProviderReadinessService and provider admission
```

It does not implement a second OpenBao resolver, S3 lifecycle client, provider
preflight client, readiness cache, or readiness system of record. S14 through
S16 will adapt those existing owner results to this vocabulary.

## Canonical Projection

`nex_runtime.dependency_readiness` defines:

```text
platform_dependency_readiness.v1
platform_dependency_readiness_aggregate.v1
```

The bounded dependency projection contains only:

```text
dependency_id
dependency_type
owner
required
configured
provisioned
reachable
authorized
ready
evidence_hash
checked_at
```

Supported initial types are `OPENBAO`, `OBJECT_STORAGE`, and
`MODEL_PROVIDER`. The evidence hash is calculated from canonical identity and
boolean state only; timestamps and raw owner evidence are excluded.

## Fail-Closed Rules

```text
ready = configured AND provisioned AND reachable AND authorized
configured != ready
missing required dependency -> aggregate NOT_READY
observed required dependency not ready -> aggregate NOT_READY
missing optional dependency -> aggregate may remain READY
undeclared, duplicate, or identity-drifted observation -> reject
```

The JSON Schema rejects additional properties, including secret-bearing
fields. The Python projection also exposes a fixed field set and never accepts
raw owner evidence.

## Contract Artifacts

```text
contracts/schemas/common/platform_dependency_readiness.v1.schema.json
contracts/examples/common/platform_dependency_readiness.ready.json
contracts/tests/negative/common/platform_dependency_readiness.secret_leak.json
```

## Verification

```text
focused tests                         = 23 passed
focused statement / branch            = 100.00% / 100.00%
Platform Slice Gate                   = 425 passed / 7 skipped
Slice statement / branch              = 100.00% / 100.00%
contract validation                   = 227 / 291 / 245 / 10
Golden Journey transition audit       = PASS
ruff / diff check                     = PASS
database migration                    = NONE
protected PostgreSQL / provider smoke = NOT REQUIRED
```

An additional broad `nex-runtime` regression run completed with `1,899 passed`
and `1 skipped`. Its package-wide historical coverage was `90.01% / 86.83%`,
so it was retained as diagnostic regression evidence rather than the S13
coverage gate. The canonical cross-platform Slice Gate scopes coverage to the
new S13 module and passed both thresholds.

## Exit

```text
shared dependency readiness vocabulary = ACTIVE
required dependency fail-closed rule    = ACTIVE
secret-free deterministic evidence      = ACTIVE
owner-specific probe duplication        = NONE
next slice                              = GB2-CA00-S14
```
