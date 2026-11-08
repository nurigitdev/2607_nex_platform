# P8-S99A: NSL UPDATE OperationKind and v0.2.1 Admission

## Scope

This compatibility Slice precedes P8-S99. It adds a bounded NSL WRITE
operation kind for mutations of existing business objects and admits the exact
NSL `0.2.1` wheel without rewriting the historical `0.2.0` release lineage.

## Implementation

- Added `OperationKind.UPDATE` in `nurigitdev/2608_nsl`.
- Preserved `CREATE` and `CREATE_DRAFT` values and fail-closed unknown values.
- Bumped the NSL package single version source to `0.2.1`.
- Added an exact Platform release profile and additive
  `deployment/locks/nsl-v0.2.1-wheel.json`.
- Restricted v0.2 runtime admission to the explicit set `0.2.0`, `0.2.1`.
- Switched new AE v0.2 worker startup to the `0.2.1` lock while retaining
  `0.2.0` validation for historical restart and evidence compatibility.
- Bound the AE public API contract hash to the admitted patch version.

No database migration, API field change, or remote provider call is part of
this Slice.

## Exact Identity

```text
NSL source revision = d53658ec2ab0b42e995fe0ebe80badd53218feec
NSL source tree     = e16863f483bd6b9e2e1503de9baaf0f58cb15521
package version     = 0.2.1
wheel               = nex_skill_language-0.2.1-py3-none-any.whl
wheel sha256        = sha256:a89ce5fde1a32749565ba0906a2f1faf1d440ff6db2dfc07c0b2a581378507cb
cryptography        = 46.0.7
```

The Platform admission runner produced the wheel twice from clean Git archives
and required byte-identical digests before isolated public API import and lock
creation.

## Verification

```text
NSL focused tests       = 98 passed
NSL authoritative gate = 2314 passed
NSL statement coverage = 99.25%
NSL branch coverage    = 98.05%
NSL wheel release      = VERIFIED
Platform admission     = PASS, reproducible_build_count=2
Platform focused       = 66 passed
Shared runtime         = 1652 passed / 1 protected skip
Changed lock module    = 100% statement / 100% branch
AE Slice Gate          = 5360 passed / 44 protected skips
AE statement coverage = 98.32%
AE branch coverage    = 96.28%
Contract validation   = 193 schemas / 257 positive / 222 negative / 9 OpenAPI
Installed readiness   = PASS, installed_distribution, package 0.2.1
```

The shared runtime regression population passed in full. Its broad service
profile includes unrelated historical modules below the current aggregate
Slice thresholds; the changed `nsl_v02_wheel_lock.py` scope itself remained at
100% statement and branch coverage. The canonical owning AE Slice Gate passed
without a threshold exception.

## Decision

P8-S99 may map:

| Canonical operation | OperationKind |
|---|---|
| `PROJECT.PROJECT.CREATE` | `CREATE` |
| `PROJECT.PROJECT.DEACTIVATE` | `UPDATE` |
| `PROJECT.MEMBERSHIP.ADD` | `CREATE` |
| `PROJECT.MEMBERSHIP.REMOVE` | `UPDATE` |
