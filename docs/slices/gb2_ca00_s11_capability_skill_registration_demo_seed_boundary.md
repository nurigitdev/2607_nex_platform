# GB2-CA00-S11: Capability / Skill Registration and Demo Seed Boundary

## Scope

S11 separates business scenario data from the Platform fact that a capability
and its exact Skill artifact exist. It adds no database migration, public API,
worker state transition, or remote-provider dependency.

## Canonical Registration

`ProductCapabilityRegistry` is the canonical, hash-protected source for exact
product capability and Skill availability. The first deployment seed is:

```text
deployment/environments/ae-product-capability-registry.v1.json
```

Each entry binds and validates:

```text
capability descriptor
exact LOCAL_SKILL binding
admitted bundle manifest reference
bundle identity
Skill ID, version, and semantic hash
registration hash
registry hash
```

Golden A preserves the distinct identities:

```text
Capability = FINANCE.CREATE_VOUCHER_DRAFT
Skill      = FINANCE.VOUCHER_DRAFT_CREATE
```

Malformed registries, duplicate capabilities, baseline conflicts, hash drift,
non-LOCAL_SKILL registrations, and Skill artifact mismatches fail closed.

## Product Activation Boundary

`finance-golden-a-vo00.v1.json` now contains only tenant-scoped business
authority and protected scenario input. Its former `admission` block was
removed. The profile is rejected if capability admission metadata is inserted
again.

Golden A product activation now requires both independent sources:

```text
business authority profile
canonical product capability registration
```

The `DomainIntentActivatorRegistry` continues to select deterministic product
behavior by capability ID. `ProductCapabilityRegistry` separately establishes
that the capability and exact admitted Skill exist. Neither registry replaces
the other.

## Runtime and Demo Seed

When no durable tenant snapshot exists, semantic admission builds the fallback
snapshot from baseline P5 capabilities plus the canonical product registry.
The P8 Demo Chairman journey seeds its durable capability snapshot from the
same registry and no longer loads either Golden A business fixture to establish
capability existence.

Demo fixtures may still supply Project, Account, user, approval target, and
scenario content. The historical controlled-WRITE worker may continue reading
those business fixtures until its later productization Slice.

The P8 Demo Compose profile and AE runtime image now inject and package:

```text
NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH
```

## Verification

```text
S11 focused registry tests             = 22 passed
cross-generation focused regression    = 102 passed / 1 protected skip
new registry statement / branch        = 99% / 100%
NeX-AE Slice Gate                      = 5,702 passed / 45 skipped
NeX-AE statement / branch              = 97.00% / 95.29%
contract validation                    = 226 / 290 / 244 / 10
ruff / diff check                      = PASS
database migration                     = NONE
PostgreSQL / remote provider            = NOT REQUIRED
```

## Exit

```text
Platform capability existence source   = CANONICAL REGISTRY
Golden A business/admission separation = ENFORCED
Capability/Skill exact binding          = FAIL-CLOSED
semantic fallback snapshot              = REGISTRY-BACKED
P8 Demo capability seed                 = FIXTURE-INDEPENDENT
CA00-DOMAIN-01                          = CLOSED
next slice                              = GB2-CA00-S12
```
