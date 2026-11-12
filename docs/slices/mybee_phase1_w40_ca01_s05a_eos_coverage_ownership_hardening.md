# W40-CA01-S05A EOS Coverage Ownership and Branch Margin Hardening

## Status

`CLOSED` on 2026-11-12.

This corrective Slice raises the NeX-EOS branch-coverage margin without changing
product behavior or duplicating existing regression cases.

## Finding

The low EOS margin was not caused by the S05 Project authorization implementation.

- The S05 `project_authorization.py` module is covered at 100% statement and
  100% branch coverage.
- The 50 branches added between the S04 and S05 EOS reports were all covered.
- The main uncovered areas were older installed-runtime boundaries:
  `approval_decision_api.py` and `ae_outbox_transport.py`.
- Existing tests already exercised those boundaries, but their filenames used
  `test_gb2_*`, `test_nex_platform_*`, and `test_nex_runtime_*` ownership
  namespaces. The NeX-EOS Slice Gate selected only `test_nex_eos_*` and
  `test_eos_*`, so valid cross-service evidence was omitted from the EOS report.
- The S04 EOS/OA entitlement synchronization regression had the same ownership
  issue and previously had to be passed to the Gate explicitly.

The W40 EOS branch trend before this correction was:

```text
S01: 3040 / 3232 = 94.06%
S02: 3068 / 3260 = 94.11%
S04: 3116 / 3312 = 94.08%
S05: 3166 / 3362 = 94.17%
```

The historical result shows a persistent test-selection margin problem rather
than a recent branch-quality regression.

## Change

The NeX-EOS service profile in `run_tiered_quality_gate.py` now permanently
includes these existing cross-owner regressions:

- `test_gb2_ca00_s20b_trust_approval_boundaries.py`;
- `test_nex_oa_eos_mybee_project_entitlement_sync.py`;
- `test_nex_platform_p8_demo_domain_composition.py`; and
- `test_nex_runtime_p8_demo_domain_activation.py`.

The selection remains narrow: four known EOS-owned integration files add only
47 tests and do not broaden the profile to all Platform or Runtime tests. A gate
unit test protects this many-to-many ownership mapping from future removal.

No production source, database schema, API, or coverage threshold changed.

## Validation

Focused gate regression:

```text
tests/test_tiered_quality_gate.py: 22 passed
cross-owner EOS evidence: 47 passed
```

NeX-EOS Slice Gate:

```text
status: PASS
commands: 5/5
tests: 1609 passed, 47 protected skips
statement coverage: 12623 / 13022 = 96.94%
branch coverage: 3196 / 3362 = 95.06%
branch improvement from S05: +30 covered branches, +0.89 percentage points
contract validation: PASS
golden journey transition audit: PASS
demo/product dependency audit: PASS
```

Coverage evidence:

- `reports/quality/mybee-w40-ca01-s05a-eos.coverage.json`

## Remaining Hotspots

The largest genuine EOS branch gaps now remain in Project application and
approval domain services. They should be covered as their business behavior is
extended, rather than by synthetic tests written only to increase the aggregate
percentage. With a 95.06% EOS baseline, W40-CA01-S06 can proceed with adequate
margin while preserving the existing 94% required threshold.

