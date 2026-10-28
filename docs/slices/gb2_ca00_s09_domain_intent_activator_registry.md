# GB2-CA00-S09: DomainIntentActivator Registry Foundation

## Scope

S09 removes the direct P8 Demo activation dependency from semantic candidate
admission. It introduces no database migration, public API change, worker,
remote-provider dependency, or business capability seed.

## Canonical Registry

`DomainIntentActivatorRegistry` is an immutable, capability-keyed registry.
Every registration binds:

```text
capability_id
version
source_identity
activator
```

Registrations are sorted by exact capability identity before projection.
Duplicate capabilities, malformed metadata, malformed activators, and unknown
required capabilities fail closed. Unknown optional capabilities resolve to no
activation. Registration and registry projections use the shared canonical
semantic SHA-256 helper and are stable across input order and replay.

## Semantic Admission Boundary

`semantic_candidate_admission` now depends only on the canonical registry and
product builder. It no longer imports `p8_demo_semantic_activation` or knows
how a domain activator is constructed.

At the S09 checkpoint the product builder temporarily adapted the explicitly
enabled P8 Demo Golden A activator. S10 subsequently replaced that adapter with
the canonical finance authority source; this paragraph records the historical
S09 boundary rather than the current product composition.

## Verification

```text
focused registry regression   = 13 passed
focused semantic regression   = 45 passed
NeX-AE Slice Gate             = 5,660 passed / 45 protected skips
NeX-AE statement / branch     = 97.05% / 95.36%
new modules statement/branch  = 100.00% / 100.00%
contract validation           = 226 / 290 / 244 / 10
ruff / diff check             = PASS
```

Protected PostgreSQL, RustFS, remote-provider, and Playwright tests are not
required because S09 changes only an in-process registry and composition
boundary.

## Exit

```text
canonical registry                    = READY
duplicate / unknown-required behavior = FAIL-CLOSED
stable projection and hash            = PASS
semantic admission direct Demo import = REMOVED
Golden A explicit compatibility       = PRESERVED
database migration                    = NONE
next slice                            = GB2-CA00-S10
```
