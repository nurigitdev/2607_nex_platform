# GB2-CA00-S20R-A: Deferred Live Runner Runtime Reconciliation

## Outcome

Status: `PASS`

Decision:

`DEFERRED_LIVE_RUNNERS_RECONCILED`

The deferred S136 and S137 live boundaries now execute the current product
runtime instead of historical calibration or smoke-only composition. The
reconciliation consumes the closed S20Q evidence without reopening HOLDOUT,
changing a threshold, or selecting another profile.

## Reconciled Runtime

The S136 replay is mapped to the current P-A permission-filtered hybrid
retrieval and five-run repeatability runner. The retired 20-case v1
calibration runner is not executed.

The S137 runner now builds the same answer-support composition used by the CX
product entry point. The primary controlled policy and its observer are
passed into the CX MVP runtime, and the redacted provider observations needed
by the reconciliation evaluator are retained in the S137 evidence.

The admitted generation identity is exact:

```text
model          = Qwen3.5-9B
revision       = hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a
deployment     = dgx-qwen3-5-9b-9116
provider port  = 9116 (not persisted in evidence)
```

The deployment ID is part of the frozen contract. A model-name or revision
match with a different deployment identity fails closed.

## Implementation

- Shared product composition:
  `services/nex-cx/nex_cx/retrieval_answer_support_runtime_composition.py`
- Frozen reconciliation design:
  `scripts/smoke/data/s136_deferred_live_runner_reconciliation_v1_design.json`
- Contract and evidence evaluator:
  `services/nex-cx/nex_cx/retrieval_deferred_live_runner_reconciliation.py`
- Protected restart-safe runner:
  `scripts/smoke/run_gb2_s20ra_deferred_live_runner_runtime_reconciliation.py`
- Protected evidence:
  `reports/live/gb2_ca00_s20ra_deferred_live_runner_runtime_reconciliation.json`

The S136 replay evidence may be reused only from `reports/live` after it has
already passed. This avoids repeating 2,241 provider requests after a later
S137 diagnostic failure. S137 is always executed after the admitted S136
evidence has passed.

No database migration, public API field, threshold, calibration profile,
provider model selection, or historical evidence was changed.

## Corrective Findings

The protected replay exposed and corrected four gaps that synthetic tests had
not detected:

1. The historical S136 runner would have recalculated the rejected v1
   calibration instead of replaying the admitted current retrieval boundary.
2. S137 constructed the CX MVP runtime without the product answer-support
   composition.
3. The generation model and immutable revision were correct, but the MO
   default deployment ID differed from the admitted Qwen3.5-9B deployment.
4. The evaluator fixture used `reranking_model_revision`; the actual S136
   evidence contract uses `reranker_model_revision`.

The protected browser smoke also removes its own answer-support operational
events and owner-scoped AE/CX rows from the test databases. It does not retain
rollback state from a previous diagnostic run.

## Protected Evidence

All 9 reconciliation checks passed:

```text
S136 database / role       = nex_cx_test / nex_cx_user
S136 embedding requests    = 1,441
S136 reranking requests    = 800
S136 five-run repeatability= STABLE
S137 databases             = nex_ae_test, nex_cx_test
S137 providers             = embedding, reranking, generation
S137 product runtime       = canonical answer-support policy active
S137 residue               = 0
HOLDOUT accessed           = false
HOLDOUT reexecuted         = false
retired v1 calibration     = not executed
```

Frozen hashes:

```text
design hash          = sha256:b0e0c6a1db1b1d3f2a289703fcac663778c30a9032aa2f13201f45a509f56fc1
contract hash        = sha256:525125e26dd462585ecd3d1832ae41d664de20f7320f4767bbaa8eb6e9e91318
S136 replay hash     = sha256:b2d1e8837e649c797e003914b056741d89c3e8fb48a937437c4293d9e75f0db0
S137 replay hash     = sha256:4b29b510cbd6b096fb62904edbeb32936861a448a94828d1b51d737ef9981841
selected policy      = sha256:c81f7a0bf3d3d72d7bbc5de1f564ada3b415f2206689c1939fcb925f172168cb
evidence hash        = sha256:d23fa8fb1fad344d7a652adc4a1580f0cafa0730652c210a843c18fc9e8f9d4e
evidence file SHA-256= 786b34a7d892f707331d8dd24e471415b33a575e98e548689a67c6473fc8e7c7
```

## Verification

```text
focused regression         = 38 passed
reconciliation module      = statement 100%, branch 100%
protected S137 replay      = 9/9 PASS, providers 3, databases 2, residue 0
protected S20R-A replay    = 9/9 PASS

NeX-CX Slice Gate          = 3,433 passed
statement coverage         = 99.24%
branch coverage            = 98.38%
contract validation        = 230 schemas, 291 examples,
                             245 negative examples, 10 OpenAPI documents
golden transition audit    = PASS, 9 registered, 1 enforced
dependency audit           = PASS, 7/7 edges
tiered Slice Gate          = 5/5 commands passed
```

## Next Boundary

`GB2-CA00-S20R: Calibration Closure and Deferred Live Matrix Replay`

S20R may consume this PASS evidence and execute the remaining deferred live
matrix. It must not rerun the one-shot HOLDOUT or reopen profile selection.
