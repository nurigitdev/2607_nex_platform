# GB2-CA00-S20Q-P-T Shadow Canary Operations and Operator Approval

## Purpose

S20Q-P-T connects the receipt-admitted answer-support shadow evaluator to the
exact live generation provider under a small, one-shot operational budget. It
adds an explicit operator approval boundary before any provider call and leaves
the current retrieval confidence policy as the unchanged fallback.

This Slice does not reopen HOLDOUT, change the threshold or profile, expose the
shadow decision to a user, activate the candidate at runtime, or authorize a
production cutover.

## Frozen Boundary

The canary is bound to the existing P-R/P-S artifacts:

```text
readiness manifest    = sha256:77fb8be58e0c06cc91e9397a2f7d0d32787de1e9b7d844dc45942035e635bf8b
runtime profile       = sha256:ffaa4cac784d4b2e22a37e6f590655f7908cfeca518cc5cf65d32149e075daa6
request profile       = sha256:220bdc921d545a4d24a0db9a2dc4e99cefb23c73418f9f790063c665cb2126da
signal design         = sha256:ff37680fed7d1964c0d674fbcca7796fe6954f6dbe4970bc84f80e1d7761ea10
shadow runtime design = sha256:dbcb4bb42a3c4517774c11d56dcac3eae5fb98f558112411495ed7050361d0b3
canary design         = sha256:80a7fb961da439f37c9442873640ab739d678b0f8d7a8be8444db8fc3d008423
canary policy         = sha256:d7e567f9b762d626fb4705c3623aad82b2e35c9394229d5ebb1a52c486b43305
public synthetic cases = sha256:7ffdc03cc7d385558a2166104ea405c5899990f21c51c2d3170c32c890a4b99b
model revision        = hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a
deployment            = dgx-qwen3-5-9b-9116
```

The one-shot policy permits six sequential provider calls, no retry beyond the
first attempt, no provider failure, a 60-second single-call ceiling, a
45-second p95 ceiling, and at most 12,000 total tokens. Disagreement is an
observed metric and is not a profile-selection signal in this Slice.

## Operator Approval

`cx_answer_support_shadow_canary_operator_approval.v1` binds:

- operator identity and a 30-minute approval window;
- the exact policy, readiness manifest, runtime profile, and provider binding;
- the maximum provider-call budget;
- `SHADOW_CANARY_EXECUTION_ONLY` scope; and
- explicit `false` values for runtime activation and production cutover.

The approval is integrity-hashed and consumed by a mode-`0600` terminal
receipt. It is not a production signing credential. A separate operator
decision remains mandatory before any user-visible or default-policy cutover.

## Runtime and Stop Conditions

`AnswerSupportShadowCanary` wraps the P-S non-interfering evaluator and:

1. serializes calls with maximum concurrency one;
2. refuses calls after the approved budget or any terminal stop;
3. immediately halts on provider binding, permission, request, or response
   contract drift;
4. halts on the first provider failure, missing latency sample, latency budget,
   or token budget breach;
5. records only sanitized counts, latency, usage, disagreement, and hashes; and
6. preserves `CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY` and the original
   user result under all shadow outcomes.

The fixture contains six public synthetic packages. HOLDOUT and private user
content are not read. Query text, candidate text, endpoint, API key, and raw
provider response are rejected from the evidence projection.

## Live Evidence

The first live execution exposed an instrumentation defect: P-S emits
fractional millisecond latency but the first controller revision accepted only
integer samples. Its false `p95=0` result and receipt were retained locally as
`*.invalid_latency_v1.json` and are not admitted evidence.

After correcting numeric latency admission and requiring one sample per
provider call, the bounded live canary was re-executed:

```text
provider HTTP calls       = 6 / 6
latency samples           = 6 / 6
provider failures         = 0
disagreements             = 1 / 6 (16.6667%, observe-only)
p95 latency               = 38,912.964 ms
maximum latency           = 38,912.964 ms
total tokens              = 2,790 / 12,000
HOLDOUT access            = no
runtime activation        = prohibited
production cutover        = prohibited
decision                  = SHADOW_CANARY_ACCEPTED_OPERATOR_REVIEW_REQUIRED
```

The authoritative ignored local artifacts are:

- `reports/live/gb2_ca00_s20qpt_shadow_canary_receipt.json`;
- `reports/live/gb2_ca00_s20qpt_shadow_canary_operations.json`.

Disabled quality-gate smoke execution no longer overwrites an existing
terminal report with `SKIPPED`.

## Verification

```text
focused tests                                = 28 passed
new product module statement / branch        = 100% / 100%
new protected runner statement / branch      = 100% / 100%
initial NeX-CX Slice Gate                     = 2,998 passed
initial NeX-CX statement / branch             = 99.11% / 98.21%
final NeX-CX Slice Gate                       = 3,006 passed
final NeX-CX statement / branch               = 99.15% / 98.38%
contract validation                           = PASS
golden journey transition audit               = PASS
demo-to-product dependency audit               = PASS
protected live provider canary                 = PASS
```

## Decision and Next Boundary

```text
decision              = SHADOW_CANARY_ACCEPTED_OPERATOR_REVIEW_REQUIRED
current user behavior = unchanged
current fallback      = unchanged
next boundary         = SEPARATE_RUNTIME_CUTOVER_OPERATOR_DECISION
```

The next boundary must consume this terminal receipt without re-running
HOLDOUT. It may decide whether to continue shadow observation, revise the
operational latency budget, or authorize a separately bounded runtime canary.
It must not infer production cutover approval from this receipt.
