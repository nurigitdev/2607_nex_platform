# CP-M1-GA-RET-02A.2: Explicit AE Test Ownership Reconciliation

## Status

- State: `CLOSED`
- Date: `2026-11-16`
- Parent: `CP-M1-GA-RET-02A`
- Entry commit: `7f011168`
- Database migration: none
- Public API change: none
- Remote provider: not required

## Goal

Make the AE Slice Gate execute current AE-owned behavior whose tests use a
MyBee transition filename rather than `test_ae_*` or `test_nex_ae_*`. The
mapping must be exact, reviewable, deterministic, and deduplicated. Broad
MyBee or Wave patterns are prohibited.

## Gate Contract

`ServiceProfile` now separates two selectors:

```text
test_patterns   conventional service namespace
owned_tests     exact cross-namespace ownership paths
```

The existing AE patterns remain unchanged. Six exact tests are admitted:

| Test | AE ownership reason |
| --- | --- |
| `test_mybee_skill_admission.py` | signed Skill and current capability-registry admission |
| `test_w40_ca02_installed_configuration_wiring.py` | installed AE process, OCI, Compose, and product admission |
| `test_w40_ca02_runtime_ownership_audit.py` | AE runtime/package ownership boundary |
| `test_w70_cp_m1_ga_ret_02.py` | active generalized registry and Golden A quarantine |
| `test_w70_s8_01d_registry_bundle_locks.py` | versioned registry/bundle release and deployment lock |
| `test_w70_s8_01e_foundation_gate.py` | AE capability foundation admission and aliases |

The plan builder validates every path below `tests/`, adds it after normal
service discovery, and deduplicates it against focused tests. Repeated plan
construction produces the same command ordering.

## Deliberate Exclusions

The mapping does not admit:

- `test_w40_ca02_installed_product_integration.py`, which directly imports
  hash-pinned Golden A source modules;
- `test_w70_cp_m1_ga_ret_01.py`, which is selection-freeze history and also
  imports historical sources;
- `test_boundary_imports.py`, which owns the domain package boundary rather
  than AE behavior; or
- `test_w70_s8_01b_tool_contract_admission.py`, whose authority is the
  MyBee/EOS contract catalog rather than AE runtime code.

These exclusions prevent historical replay or unrelated domain tests from
being selected merely to increase AE coverage.

## Reconciliation Found During Admission

Running the six tests together exposed two stale deployment assertions. They
still expected `ae-product-capability-registry.mybee-m1.v1.json` and the old
Golden A rollback receipt after RET-02 had promoted:

```text
ae-product-capability-registry.mybee-m1.v2.json
ae-mybee-m1-runtime-activation.v2.json
ae-mybee-m1-generalized-rollback.v1.json
```

The signed M1 checkpoint continues to verify its immutable v1 registry hash.
Tests now explicitly distinguish that historical signing input from the v2
canonical runtime registry instead of rewriting the signed baseline.

## Coverage Result

| Metric | A1 Gate | A2 Gate | Delta |
| --- | ---: | ---: | ---: |
| Aggregate statement | 95.8909% | 96.3908% | +0.4999 pp |
| Aggregate branch | 94.0261% | 94.5663% | +0.5401 pp |
| Active product statement | 96.5514% | 97.0695% | +0.5181 pp |
| Active product branch | 94.3350% | 94.8851% | +0.5501 pp |
| Compatibility statement / branch | 61.9238% / 62.9630% | unchanged | 0 |
| Historical statement / branch | 86.8421% / 81.7647% | unchanged | 0 |

`product_capability_releases.py` moved from no Gate execution to statement
`98.9305%` and branch `96.6667%`. Historical scope coverage did not change,
which proves the margin came from current product ownership rather than
Golden A replay.

The A2 result exceeds the RET-02A closure targets of statement `96.25%` and
branch `94.50%`. This does not remove the planned `.4` and `.5` obligations to
cover meaningful denial, ambiguity, replay, and recovery branches.

## Verification

```text
quality-Gate selector regression      23 passed
owned-test focused regression         204 passed
AE Slice Gate                         6,223 passed / 46 protected skips
AE Slice Gate files                   434
AE Slice Gate commands                5 / 5, PASS
AE Slice Gate duration                524.450 seconds
aggregate statement / branch          96.3908% / 94.5663%
active product statement / branch     97.0695% / 94.8851%
historical active/deployment conflict 0 / 0
ruff                                  PASS
git diff --check                      PASS
```

Generated evidence remains under ignored report paths:

```text
reports/quality/mybee-w70-ga-ret-02a2-ae.coverage.json
reports/coverage/mybee-w70-ga-ret-02a2-ae-ownership-inventory.json
```

## Exit

Explicit AE test ownership is reconciled without widening a wildcard, changing
the source target, or executing historical modules. The next boundary is
`CP-M1-GA-RET-02A.3: Ownership-Aware Coverage Reporting and Quarantine Guard`.
