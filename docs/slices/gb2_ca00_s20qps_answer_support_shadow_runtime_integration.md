# GB2-CA00-S20Q-P-S Answer-Support Shadow Runtime Integration

## Purpose

S20Q-P-S installs the receipt-admitted answer-support evaluator behind the CX
permission-filtered retrieval package boundary. The new evaluator is shadow
only: it observes an already-completed primary package and cannot replace or
mutate the existing retrieval confidence decision.

The Slice does not reopen HOLDOUT, select another profile or threshold, enable
production cutover, or make a live provider call during protected acceptance.

## Source Audit and Refactoring

The existing CX package runtime produced the primary package directly. The
answer-support candidate profile uses generation-backed support and
contradiction signals and therefore could not be inserted into the existing
confidence consumer without changing behavior.

The runtime now exposes an optional `HybridRetrievalShadowObserver` seam. The
primary package is completed first and defensive copies of the private query
inputs and package are passed to the observer. Observer or telemetry failures
are contained and the original package is returned unchanged.

The optional observer is threaded through:

- `PermissionFilteredHybridPackageRuntime`;
- `build_permission_hardened_hybrid_runtime()`;
- `build_cx_mvp_runtime()`; and
- `build_cx_mvp_runtime_composition()`.

The default remains `None`; installed startup activation is not performed by
this Slice.

## Frozen Binding

```text
readiness manifest = sha256:77fb8be58e0c06cc91e9397a2f7d0d32787de1e9b7d844dc45942035e635bf8b
runtime profile    = sha256:ffaa4cac784d4b2e22a37e6f590655f7908cfeca518cc5cf65d32149e075daa6
request profile    = sha256:220bdc921d545a4d24a0db9a2dc4e99cefb23c73418f9f790063c665cb2126da
signal design      = sha256:ff37680fed7d1964c0d674fbcca7796fe6954f6dbe4970bc84f80e1d7761ea10
profile id         = answer-support-contradiction-aware-v2
threshold          = 0.46375 inclusive
model revision     = hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a
deployment         = dgx-qwen3-5-9b-9116
```

Manifest, runtime profile, request profile, provider alias, immutable model
revision, deployment, score semantics, or threshold drift fails the shadow
decision closed. It does not fail the primary retrieval request.

## Runtime Behavior

`AnswerSupportShadowRuntime`:

1. admits only `grounded_answer` and `document_generation` packages;
2. receives only owner-authorized evidence after permission filtering;
3. transports private query and candidate text ephemerally to the generation
   client;
4. requires reasoning-disabled deterministic JSON output;
5. normalizes provider output into text-free answer-support evidence;
6. applies the frozen five-feature profile and threshold;
7. emits an `OBSERVED`, `SKIPPED`, or `FAILED` shadow outcome; and
8. records sanitized latency, provider usage, disagreement, and failure data
   through `cx.retrieval.answer_support_shadow` operational events.

No raw query, candidate text, free-form rationale, provider response text, or
candidate truth is included in the outcome or operational event.

## Non-Interference and Failure Policy

- Shadow decisions are not added to the user-facing retrieval package.
- The observer receives defensive copies and cannot mutate the primary result.
- Provider failure and malformed output become `SHADOW FAILED / NOT_READY`.
- Provider binding drift becomes `SHADOW FAILED / NOT_READY`.
- Telemetry sink failure is contained.
- Ineligible purpose and empty evidence avoid provider calls.
- The current active retrieval confidence policy remains the exact fallback.

## Protected Evidence

The protected runner consumes the existing P-R readiness manifest. It runs one
deterministic successful evaluation, one ineligible-purpose skip, and one
deliberate deployment-drift failure.

```text
protected shadow runtime = PASS
outcomes                 = OBSERVED, SKIPPED, FAILED
provider calls           = 2 deterministic local calls
database calls           = 0
HOLDOUT reexecution      = no
primary package changed  = no
private text persisted   = no
runtime activation       = prohibited
production cutover       = prohibited
```

The local ignored evidence path is
`reports/live/gb2_ca00_s20qps_answer_support_shadow_runtime.json`.

## Verification

```text
focused regression                       = 97 passed
shadow product/runner/observability code = 100% statement / 100% branch
NeX-CX Slice Gate                        = 2,978 passed
NeX-CX statement coverage                = 99.14%
NeX-CX branch coverage                   = 98.36%
contract validation                      = PASS
golden journey transition audit          = PASS
demo-to-product dependency audit         = PASS
```

## Decision and Next Boundary

```text
decision              = SHADOW_RUNTIME_EVALUATOR_INTEGRATED_NOT_ACTIVATED
current user behavior = unchanged
next boundary         = SHADOW_CANARY_OPERATIONS_AND_OPERATOR_APPROVAL
```

The next Slice may install the observer in an explicitly enabled canary
composition and collect real provider latency, failure-rate, disagreement, and
capacity evidence. It must preserve the current fallback and require explicit
operator approval before any user-visible or production cutover.
