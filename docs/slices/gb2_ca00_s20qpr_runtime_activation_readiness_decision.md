# GB2-CA00-S20Q-P-R Runtime Activation / Readiness Decision

## Purpose

S20Q-P-R consumes the terminal S20Q-P-Q PASS receipt as immutable evidence and
decides the next runtime boundary. It does not reopen the HOLDOUT, call a model
provider, select another profile, or change the frozen threshold.

## Source Audit

The installed CX retrieval runtime currently consumes
`cx_retrieval_confidence_calibration_profile.v1`. That profile projects
reranker score, reranker margin, normalized RRF, and channel-support signals.

The admitted S20Q-P-Q candidate instead uses the separate
`cx_answer_support_runtime_profile.v1` contract. It requires provider-backed
answer-support and contradiction evidence before applying the frozen package
threshold. No installed retrieval consumer currently performs that projection.

The HOLDOUT result is therefore sufficient to admit integration readiness but
is not sufficient to silently replace the current runtime policy.

## Frozen Evidence Binding

```text
execution id        = s20qpq-4ba9f4f7633136589cda7d17
receipt status      = PASS
receipt hash        = sha256:1bbfa3983dcad9b0aa39ace9be8eca57dfbd4a7bc1484b2f01366c8ccf5caa68
evaluation hash     = sha256:e3696095c0fb198ce35d65b291e3121d8a099e6a4fafb993d28be265f3c9a28c
profile id          = answer-support-contradiction-aware-v2
profile hash        = sha256:495bbc63c50affddd70e90c97fc27655c94c5eeabf890a5f13f5c2df5f90a31e
threshold           = 0.46375
model revision      = hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a
dataset semantic    = sha256:594209203d25b0a87e6fd136b6794bdc30058a5eb45b7e2c8ff27523bd7f1757
provider evaluations = 40
provider HTTP calls  = 40
```

The readiness contract additionally binds the complete P-Q report hash and
the complete terminal receipt document hash. Receipt, evaluation, profile,
request profile, dataset, provider revision, execution identity, or metric
drift fails closed.

## Decision

```text
readiness decision     = READY_FOR_SHADOW_RUNTIME_INTEGRATION
activation status      = NOT_ACTIVATED
candidate profile      = READY_FOR_SHADOW
HOLDOUT reexecution    = prohibited / not required
runtime cutover        = prohibited in this Slice
current runtime policy = unchanged
provider calls         = 0
database calls         = 0
```

The generated candidate profile hash is:

```text
sha256:ffaa4cac784d4b2e22a37e6f590655f7908cfeca518cc5cf65d32149e075daa6
```

The protected readiness manifest hash is:

```text
sha256:77fb8be58e0c06cc91e9397a2f7d0d32787de1e9b7d844dc45942035e635bf8b
```

## Activation Boundary

The next boundary is `ANSWER_SUPPORT_SHADOW_EVALUATOR_AND_CANARY`:

1. add the answer-support evaluator as a shadow-only retrieval stage;
2. keep shadow decisions invisible to users and outside current READY gating;
3. fail closed on provider, request-profile, model revision, dataset, profile,
   or threshold drift;
4. measure latency, failure rate, provider capacity, disagreement, and cost;
5. retain `CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY` as fallback and exact
   rollback target;
6. require explicit operator approval before canary or production cutover.

The existing PASS receipt remains the acceptance evidence. This boundary does
not require or permit a second HOLDOUT execution.

## Implementation

- `services/nex-cx/nex_cx/retrieval_answer_support_runtime_readiness.py`
  validates receipt/report integrity and emits the immutable readiness
  manifest and `READY_FOR_SHADOW` candidate profile.
- `scripts/smoke/data/s136_answer_support_runtime_activation_readiness_v1_design.json`
  freezes the source hashes, readiness requirements, shadow-first rollout,
  fallback, rollback, and no-reexecution rules.
- `scripts/smoke/run_gb2_s20qpr_runtime_activation_readiness.py` reads only the
  existing protected P-Q evidence. It performs no provider or database calls.

## Verification

```text
focused product/runner tests          = 13 passed
new product statement/branch          = 100% / 100%
new protected runner statement/branch = 100% / 100%
protected receipt-backed readiness    = PASS
readiness decision                    = READY_FOR_SHADOW_RUNTIME_INTEGRATION
activation status                     = NOT_ACTIVATED
HOLDOUT reexecution                   = prohibited
provider calls / database calls       = 0 / 0
NeX-CX service regression             = 2,962 passed
repository statement coverage         = 99.14%
repository branch coverage            = 98.35%
contract validation                   = PASS (230 schemas, 291 examples,
                                         245 negative examples, 10 OpenAPI)
golden journey transition audit       = PASS
demo-to-product dependency audit      = PASS
```

The ignored local evidence path is
`reports/live/gb2_ca00_s20qpr_runtime_activation_readiness.json`.
