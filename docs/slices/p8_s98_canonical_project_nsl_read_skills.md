# P8-S98: Canonical Project NSL READ Skills and Tools

## Status

Completed on 2026-10-25.

## Scope

P8-S98 added the first flat P8.10 Project operation source set to the owning
NSL repository. Existing historical two-segment Skills and Tools were not
renamed or modified.

The admitted READ identities are:

```text
PROJECT.PROJECT.GET@1.0.0
PROJECT.PROJECT.LIST@1.0.0
PROJECT.MEMBERSHIP.LIST@1.0.0
```

Each Skill is deterministic and `READ_ONLY`, uses exactly one matching READ
Tool, and requires `project:project:read`. Collection execution is bounded to
100 rows. Tenant and membership filtering remains authoritative at the EOS
adapter/service boundary; the Skill does not access a database directly.

## Artifact Identity

The Skill artifact set and runtime wheel are intentionally separate identities:

```text
NSL artifact source revision = 82bc0fcbeb0de59bdc0aa3785c589e5515b24280
artifact manifest sha256     = sha256:fb1b2f15eff60e0439ddd81c0fd7475d2e6214fa610e0401412baf717319f799
runtime wheel source         = c0a8d4e125ee129c4556d896356237bb3973582d
runtime wheel sha256         = sha256:862958a5eab982a71bec5ee58b9e530867d6c25f65d8b770efb29ca78ce7f135
```

The runtime package did not change, so the existing admitted wheel lock was
not rewritten. `artifact_manifest.json` binds each `.ns` source digest, the
shared Tool catalog digest, and the compiler-produced semantic hash.

## Semantic Hashes

```text
PROJECT.PROJECT.GET
  sha256:31b08c9032fb4c244e5a47a7371dad4df4b80270dfa6d69fd431a9dfeb6b29e8
PROJECT.PROJECT.LIST
  sha256:36ef806f56afb96bd3cdf97ce30667824030c98489accc39c3f87635911a7649
PROJECT.MEMBERSHIP.LIST
  sha256:16c5d8cd1a7319b2cc3d46a724af25e9158a8016a39d43f04eb4abbafda6c13f
```

## Verification

NSL native focused tests:

```text
5 passed
```

NSL mandatory full gate:

```text
2314 passed
statement coverage = 99.25% (minimum 99%)
branch coverage    = 98.05% (minimum 98%)
traceability/readiness/performance = PASS
```

Platform actual-source protected smoke:

```text
source revision, manifest digest, wheel lock = exact
all three sources recompiled with admitted wheel = exact semantic hashes
EOS OpenAPI operation identity alignment = PASS
2 passed / 0 skipped
```

Platform S98 Slice Gate:

```text
674 passed / 22 expected protected skips
statement coverage = 98.99%
branch coverage    = 98.43%
contract validation = 193 schemas / 257 positive / 222 negative / 9 OpenAPI
result = PASS
```

## Exit Decision

P8-S98 is closed. Canonical Project READ Skills and Tools now have native NSL
source, exact artifact admission evidence, and matching EOS operation
identities. P8-S99 may add the governed WRITE source set while reusing the
existing P8 controlled-WRITE runtime.
