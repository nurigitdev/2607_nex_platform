# UXM-S18 UX Acceptance v2 Contract

## Outcome

PASS / CLOSED. React v2 now has a standalone, deterministic acceptance
contract that does not depend on the legacy page DOM or its historical
screenshot selectors.

## Frozen Contract

```text
schema                  = ae_web_ux_acceptance.v2
desktop viewport        = 1440 x 900
mobile viewport         = 390 x 844
minimum control target  = 24 x 24 px
```

Stable region names:

```text
shell / sidebar / topbar / main
workspace / context / composer / primary-result
```

The region profiles distinguish login, application, workspace, and
workspace-result screens. A mobile sidebar may be visually replaced by the
mobile navigation while retaining a stable structural region in the DOM.

## Invariants

The evaluator returns fixed check IDs for:

```text
Korean document language
exactly one visible main and h1
required regions present
no horizontal overflow
all visible controls named
minimum target >= 24 px
visible focus contract
non-overlapping primary regions
no runtime debug leakage
no direct service request
no protected material leakage
```

The evaluator fails closed and reports only counts, check results, and failed
check IDs. It does not retain DOM text, request bodies, credentials, or URLs.

## Source Integration

`data-ux-region` markers were added to Login, ApplicationShell, Workspace,
Composer, Context, and BusinessResult components. They are semantic test
anchors only and do not change backend contracts, layout, routing, or user
behavior.

The matching JSON Schema is stored at:

```text
contracts/schemas/service/nex_ae_web/ux_acceptance.v2.schema.json
```

## Verification

```text
focused acceptance/component tests          = PASS, 28 tests / 3 files
contract schema validation                  = PASS, 31 tests
browser unit regression                     = PASS, 413 tests
React component regression                  = PASS, 124 tests / 28 files
TypeScript typecheck                        = PASS
modern production import audit              = PASS, 51 files
modern browser security audit               = PASS, 52 files
design token consistency                    = PASS, 146 variables / 15 components
React v2 production build                   = PASS
Playwright application of v2 receipt        = DEFERRED TO UXM-S19
PostgreSQL / remote providers               = NOT REQUIRED
```

The existing Vite bundle-size advisory remains non-blocking and unchanged.

## Decision

```text
UXM-S18 = PASS / CLOSED
Legacy-independent UX acceptance = FROZEN
UXM-S19 = AUTHORIZED
```
