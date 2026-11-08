# GB2-CA00-S18B Canonical Platform Environment and Trust Bootstrap Contract Promotion

## Scope

S18B promotes the installed current Platform from the historical P8-DEMO
environment and trust names to a product-owned canonical contract. It changes
no database schema, business API, seed data, or registry publication behavior.

## Decisions

- The final Compose layer is canonical and follows the additive P9 WA layer.
- All eight service owners use `CANONICAL_PLATFORM`; twelve API/worker
  processes expose the same final boundary and startup profile.
- Active secret references, generations, credential bootstrap, calibration,
  and Golden Journey inputs use canonical names.
- OpenBao materialization remains owner-scoped and fail-closed. API and worker
  processes for one owner deliberately share that owner's AppRole and service
  principal, while no credential crosses an owner boundary.
- OA provisions seven non-OA canonical service principals and generation-bound
  client credentials. Provisioning is replay-safe and rejects a generation
  already bound to different secret material.
- Each non-OA process exchanges its bootstrap credential for audience-scoped,
  RS256-signed startup tokens. The token profile is valid only for
  `staging_live` plus `CANONICAL_PLATFORM`, expires after 24 hours, and is
  reacquired after restart.
- P8-DEMO token and environment support remains additive only for historical
  wrappers and tests. It is not an active canonical Compose contract.
- WA is included in secret inventory, service-principal provisioning, trust
  grants, TLS admission, Compose environment admission, and release topology.

## Fail-Closed Controls

- Raw secret input is rejected when an owner-scoped reference is required.
- OpenBao references must match owner, environment name, namespace, and
  explicit version.
- Resolver metadata and secret values are validated before process launch.
- Startup token exchange verifies issuer, signature, audience, scope, owner,
  deployment boundary, profile, and exact bounded lifetime.
- Bootstrap credentials are removed from the child process environment after
  token issuance.
- Canonical source and rendered-Compose admission reject active
  `NEX_P8_DEMO_*` variables and `p8_demo_*` resources.

## Compatibility Boundary

Historical `run_p8_demo_*` commands remain thin aliases. Canonical Python and
AE Web entrypoints accept canonical variables; the web wrapper translates them
only when invoking the frozen historical Playwright harness. Legacy variable
constants in compatibility code are therefore not part of the installed
runtime environment contract.

## Verification

```text
focused canonical trust/bootstrap/provisioning       = 43 passed
new ownership modules statement/branch coverage      = 99.42% / 97.87%
combined trust/token/Compose regression               = 252 passed
combined branch-aware coverage                        = 96.27%
AE Web regression                                     = 404 passed
Platform Slice Gate                                   = 410 passed / 7 skipped
Platform Slice Gate statement/branch coverage         = 97.35% / 95.95%
contract validation                                   = 227 / 291 / 245 / 10
Golden Journey transition audit                       = PASS (9 registered)
Demo-to-product dependency audit                      = PASS (7/7 edges)
canonical trust/installed/Golden source admission     = PASS
actual Docker Compose render admission                = PASS (17 services / 9 images)
```

The seven skipped Platform tests are separately protected PostgreSQL smoke
profiles and were not silently treated as executed. This Slice changes no
database contract and therefore does not claim those protected profiles as
S18B evidence.

No registry push, database mutation, or live service startup is performed by
this Slice.
