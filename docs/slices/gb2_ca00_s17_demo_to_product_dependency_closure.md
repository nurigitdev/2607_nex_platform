# GB2-CA00-S17 Demo-to-Product Dependency Closure

## Status

```text
Slice                               = GB2-CA00-S17
Status                              = CLOSED
Canonical owner                     = Platform
Database migration                  = NONE
Full Gate #2                        = PASS
Next Slice                          = GB2-CA00-S18
```

## Goal

Close the Demo-to-Product dependency direction. Canonical product runtime
modules must remain authoritative, while the historical P8-DEMO paths remain
thin compatibility and acceptance wrappers.

## Product Dependency Boundary

The repository audit scans every Python source below `services/` with the AST
parser. Canonical product modules fail closed when they import any of these
Demo-owned dependencies:

```text
demo_fixture
demo_processes
p8_demo_runtime_composition
p8_demo_semantic_activation
```

The current inventory contains 671 canonical product files and no forbidden
dependency. Parse failures, a missing source inventory, missing wrappers, or a
missing canonical compatibility edge also fail the audit.

## Historical Compatibility Wrappers

Only these five explicitly inventoried historical wrappers may retain a Demo
name or dependency:

```text
services/_shared/nex_runtime/demo_compose.py
services/_shared/nex_runtime/demo_oci_release.py
services/nex-ae-api/nex_ae_api/demo_runtime.py
services/nex-ae-api/nex_ae_api/p8_demo_controlled_skill.py
services/nex-ae-api/nex_ae_api/p8_demo_semantic_activation.py
```

This allowlist is exact. A missing wrapper is reported as drift rather than
silently removing the P8 compatibility surface.

## Canonical Compatibility Edges

The audit proves seven source-backed edges:

```text
P8 trust admission       -> nex_runtime.openbao_provisioning
P8 object-storage gate   -> nex_runtime.object_storage_provisioning
DGX provider preflight   -> nex_mo.model_provider_admission
P8 runtime composition   -> nex_ae_api.runtime_composition
P8 S10B smoke            -> P8 composition compatibility wrapper
P8 S10C result closure   -> P8 S10B installed runtime
P8 S11 Golden A          -> S10 + S10B + product capability registry
```

All seven edges pass. Current Platform components are therefore the source of
truth; P8-DEMO keeps only compatibility and Golden Journey acceptance duties.

## Permanent Quality Guard

The executable audit is installed in both gate paths:

```text
scripts/quality/run_demo_product_dependency_audit.py
scripts/quality/run_tiered_quality_gate.py
scripts/quality/run_quality_gate.sh
```

Slice, Checkpoint, and Full gates now reject future product-owned imports of
the retired Demo runtime and fixture boundaries. The generated report contains
only path, line, finding code, and bounded dependency metadata; it contains no
payload content or secrets.

## Historical P8 Compatibility

Focused regressions retained the installed journey surfaces:

```text
P8-DEMO S10 installed domain acceptance   = PASS
P8-DEMO S10B installed runtime             = PASS
P8-DEMO S10C result closure                = PASS
P8-DEMO S11 Golden A                       = PASS
```

The combined historical and current readiness regression completed with 133
passing tests.

## PostgreSQL Protected Evidence

The S08 protected topology acceptance was executed against all eight actual
test databases:

```text
nex_oa_test
nex_ae_test
nex_cx_test
nex_mo_test
nex_ag_test
nex_wc_test
nex_eos_test
nex_wa_test
```

It exercised the promoted AE runtime worker, WC event-delivery worker, and EOS
outbox publisher, including migration, restart/replay, and cleanup. The test
passed without residual test rows.

## Verification

```text
S17 focused regression                 = 8 passed
S17 module statement / branch          = 100.00% / 100.00%
historical/current focused regression  = 133 passed
actual PostgreSQL protected topology   = PASS (8 databases, 3 promoted workers)
canonical product inventory            = 671 files
explicit Demo wrappers                 = 5/5
canonical compatibility edges          = 7/7
forbidden dependency findings          = 0
Repository Full Gate #2                = 18,577 passed / 131 skipped
Repository Full Gate duration          = 1,940.593 seconds (pytest phase)
Repository statement / branch          = 96.13% / 95.31%
contract validation                    = 227 / 291 / 245 / 10
Golden Journey transition audit        = PASS
Demo-to-Product dependency audit       = PASS
ruff / diff check                      = PASS
```

The first Full Gate attempt passed every test but reported 95.89% statement
coverage because the protected PostgreSQL topology was not enabled. The second
run enabled the actual S08 protected path and passed at 96.13%. No coverage
threshold was reduced and no source exclusion was added.

Ignored local evidence is available at:

```text
reports/quality/demo-product-dependency-audit.json
reports/coverage/gb2-ca00-s17-protected/coverage.json
reports/coverage/gb2-ca00-s17-protected/junit.xml
```

## Exit

```text
canonical product depends on Demo runtime    = NO
historical P8 compatibility                  = PRESERVED
current Platform components                  = AUTHORITATIVE
future dependency drift                      = FAIL-CLOSED
database migration                           = NONE
Full Gate #2                                 = PASS
next slice                                   = GB2-CA00-S18
```
