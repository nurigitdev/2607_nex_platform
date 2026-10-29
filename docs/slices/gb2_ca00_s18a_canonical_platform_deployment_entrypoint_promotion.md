# GB2-CA00-S18A Canonical Platform Deployment Entrypoint Promotion

## Scope

S18A removes P8-DEMO naming from the active current-platform deployment path.
It does not delete historical acceptance, change a database schema, add a
business feature, or push an image to a registry.

## Decisions

- Active Compose and Traefik overlays use `canonical-platform` names.
- Active OCI and deployment commands use `canonical_platform` names.
- Host-side semantic calibration input uses the canonical Platform variable;
  legacy P8 wrapper input is translated only at the compatibility boundary.
- The complete release set is the current nine-image catalog, including WA.
- Package admission covers all eleven current background processes.
- Former `build_p8_demo_*`, `check_p8_demo_*`, and active
  `run_p8_demo_*` commands are thin compatibility wrappers.
- True demo seed, database guardrail, and historical S10B/S10C/S12 evidence
  remain explicitly P8-DEMO scoped.
- The seven-core guarded migration closure remains bounded; WA migration and
  backup admission are still owned by the admitted P9 lifecycle.
- The Slice Gate exposed S18 fixture changes whose outer bundle digests had
  not been recomputed. The lock now records the exact tracked Demo and base
  fixture bytes; no fixture content or business seed was changed by S18A.

## Runtime And Evidence Boundary

The canonical Golden Journey is now the registered installed-platform runner.
GB2 S18 invokes its public execution API and no longer imports the private P8
S11 implementation. Current topology admission reads the S143, S146,
canonical, and P9 WA Compose layers and proves nine artifacts, twenty packaged
processes, and the additive WA API/consumer pair.

The WA consumer now supports isolated package admission. In package mode its
`--check` path verifies importability and executable identity without opening
PostgreSQL, resolving a secret, or claiming work.

## Verification

```text
focused canonical deployment regression        = 230 passed
nex-runtime broad regression                    = 1,956 passed / 1 skipped
owned-module statement coverage                 = 97.62%
owned-module branch coverage                    = 98.00%
current installation statement / branch         = 100.00% / 100.00%
WA consumer statement / branch                  = 95.60% / 96.15%
contract validation                             = 227 / 291 / 245 / 10
Golden Journey transition audit                 = PASS (9 registered, 1 enforced)
Demo-to-product dependency audit                = PASS (7/7 edges)
canonical and compatibility source-only CLIs    = PASS
actual OCI release build                         = PASS (9 images / 11 checks)
actual Docker Compose render admission           = PASS (17 services / 9 images)
```

The standard package-wide `nex-runtime` Slice Gate executed all 1,956 tests
and exposed the stale S18 lock before reaching its post-test checks. Its broad
historical package coverage remains 88%, so S18A uses the established scoped
95/94 gate for the two changed owner modules and runs contracts and boundary
audits separately. No threshold was reduced and no source was excluded from
the scoped measurement.

The canonical builder rejects a dirty tracked/build-context tree. The complete
nine-image evidence run used a clean S18A commit, admitted all non-root image
identities and package checks, and performed no registry push. Docker Compose
then rendered the four-layer current topology with seventeen services and no
raw secret or test-database input. Live service startup remains an explicit
protected operator action.
