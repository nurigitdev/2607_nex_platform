# GB2-CA00-S20R: Calibration Closure and Deferred Live Matrix Replay

## Scope

Status: `PASS / CLOSED`

Decision: `CALIBRATION_CLOSED_DEFERRED_MATRIX_PASSED`

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

## Protected Live Acceptance

The protected matrix completed all six stages in the frozen order:

```text
S136 = PASS_REUSED_FROM_S20R_A
S137 = PASS_REUSED_FROM_S20R_A
S140 = PASS
S147 = PASS
S149 = PASS
S150 = PASS
checks = 20/20 PASS
```

The current installed S149 journey used actual PostgreSQL, OpenBao, RustFS,
Docker Compose, Playwright, and the admitted Qwen3.5-9B generation provider.
S150 verified the current fail-closed and restart matrix. S147 and S150 both
reported zero residue, and the S149 queue state remained stable.

The one-shot HOLDOUT remained sealed throughout execution:

```text
HOLDOUT accessed   = false
HOLDOUT reexecuted = false
profile changed    = false
threshold changed  = false
```

Frozen acceptance hashes:

```text
contract hash        = sha256:9d8969c39673cbfff6c322d5f945843d10611e2f2e6d26560709bc2902ab437e
selected policy hash = sha256:c81f7a0bf3d3d72d7bbc5de1f564ada3b415f2206689c1939fcb925f172168cb
evidence hash        = sha256:2a0dc7060794b5737401e445da05258c3bfe90335f5c49095dc9306f24f5c15a
```

## Build and Runtime Evidence

The current canonical release build completed from source revision
`c53b3e3606f9178f4f60689c2330fbeec44871a5`:

```text
OCI artifacts               = 9/9
manifest digests            = 9/9
non-root images             = 9/9
background/package checks   = 11/11
registry push               = false
release set digest          = sha256:2abc6b14ebeabfa59a6a5bf9db0b8b45519a36746307e9347e678b905f1af16b
AE NSL runtime image digest = sha256:230655a6eb8d7ba9cf0375b0d712a9df94772104f2e982a79484e9fd488e4c2d
AE runtime user             = 65532:65532
NSL skill version           = 1.1.0
```

The initial protected S149 attempt observed the DGX GPU at 96 percent and the
generation provider correctly failed closed with `504 PROVIDER_TIMEOUT` at
the frozen 60-second MO-to-vLLM boundary. No timeout, threshold, profile, or
policy was relaxed. A read-only capacity check later observed the GPU idle,
and the exact same admitted configuration passed the complete matrix. This is
retained as co-resident capacity evidence rather than treated as a product
correctness defect.

## Repository Full Gate

```text
result                    = PASS (exit 0)
tests                     = 20,351 passed, 133 protected skips
duration                  = 2,539.74 seconds
statement coverage        = 96.74% (threshold 96.00%)
branch coverage           = 96.02% (threshold 94.00%)
product statement/branch  = 98.67% / 97.33%
harness statement/branch  = 94.18% / 92.97%
contracts                 = 230 schemas, 291 examples,
                            245 negative examples, 10 OpenAPI documents
AE Web Node regression    = 404 passed
golden transition audit   = PASS, 9 registered, 1 enforced
dependency audit          = PASS, 7/7 edges
```

The protected S20R matrix supplies the actual database, provider, Compose,
and browser evidence that the default Full Gate intentionally skips. S20R is
therefore closed without reopening calibration or repeating HOLDOUT.
