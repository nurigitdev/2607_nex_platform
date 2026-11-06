# GB2-CA00-S20R: Calibration Closure and Deferred Live Matrix Replay

## Scope

Status: `IMPLEMENTED / LIVE ACCEPTANCE PENDING`

S20R consumes the immutable S20Q closure and S20R-A runtime reconciliation.
It does not reopen HOLDOUT, select another profile, change a threshold, or
alter the admitted provider revisions.

The historical deferred matrix is replayed in this order:

1. S136 current retrieval replay from S20R-A.
2. S137 current grounded-generation replay from S20R-A.
3. S140 protected release-candidate matrix.
4. S147 actual MO provider rollout and persistence acceptance.
5. S149 current canonical installed golden journey.
6. S150 current AE/WC/EOS fail-closed restart acceptance.
7. Repository Full Gate.

## Current Runtime Mapping

The original S149/S150 runners predate WC, EOS, and WA. They require the
retired six-image S142 release set and five-database topology. Re-executing
those runners would test a historical deployment rather than the current
product.

S20R therefore preserves the requirement semantics and maps them to the
current nine-image canonical topology:

- S149 uses `run_gb2_ca00_s18_installed_current_platform_golden_journey.py`.
- S150 uses `run_gb2_ca00_s19_fail_closed_restart_acceptance.py`, followed by
  the Repository Full Gate.

This mapping is frozen in
`scripts/smoke/data/gb2_s20r_calibration_closure_deferred_live_matrix_v1_design.json`.
It adds no migration or public API change.

## Provider Binding

```text
embedding  = Qwen3-Embedding-4B
revision   = hf:5cf2132abc99cad020ac570b19d031efec650f2b

reranking  = Qwen3-Reranker-4B
revision   = hf:22e683669bc0f0bd69640a1354a6d0aebcfeede5

generation = Qwen3.5-9B
revision   = hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a
deployment = dgx-qwen3-5-9b-9116
reasoning  = disabled
```

The canonical installed journey previously embedded `Qwen3.5-4B`. It now
requires the generation model, immutable revision, and deployment identity
from the admitted runtime environment. Missing identity fails before database
or provider execution.

## Implementation

- Contract and evaluator:
  `services/_shared/nex_runtime/calibration_deferred_live_matrix.py`
- Protected runner:
  `scripts/smoke/run_gb2_s20r_calibration_closure_deferred_live_matrix.py`
- Frozen design:
  `scripts/smoke/data/gb2_s20r_calibration_closure_deferred_live_matrix_v1_design.json`
- Protected evidence:
  `reports/live/gb2_ca00_s20r_calibration_closure_deferred_live_matrix.json`

The runner is opt-in, test-profile-only, fail-fast, and redacts all database
URLs, provider endpoints, and API keys. S136/S137 are consumed from the
already passing S20R-A evidence and are not repeated.

## Verification

Implementation verification before protected execution:

```text
focused regression       = 36 passed
shared runtime regression= 2,116 passed, 1 skipped
platform Slice Gate      = 459 passed, 8 protected skips
Gate commands            = 7/7 PASS
contract/evaluator       = statement 100%, branch 100%
runner                    = statement 100%, branch 96.67%
combined focused coverage= statement 100%, branch 98.08%
contract validation      = 230 schemas, 291 examples,
                           245 negative examples, 10 OpenAPI documents
non-live admission       = READY
HOLDOUT accessed         = false
HOLDOUT reexecuted       = false
```

Protected live matrix, zero-residue results, Repository Full Gate metrics, and
the final As-Built decision are recorded after execution.
