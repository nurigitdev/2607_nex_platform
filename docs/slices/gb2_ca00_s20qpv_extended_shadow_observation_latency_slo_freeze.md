# GB2-CA00-S20Q-P-V Extended Shadow Observation and Latency SLO Freeze

## Outcome

`GB2-CA00-S20Q-P-V` is complete. The boundary collected a new 30-sample,
operator-approved, public-synthetic shadow observation against the admitted
generation provider and froze latency meanings independently from one another.

The decision is:

```text
BACKGROUND_SLO_MET_ASYNC_ISOLATION_REQUIRED
```

This is not a runtime activation or production cutover decision. The current
retrieval confidence policy remains authoritative.

## Frozen Latency Contract

| Boundary | Frozen value | Meaning |
| --- | ---: | --- |
| Interactive end-to-end p95 | 8,000 ms | Existing protected-live user-path objective |
| Background answer-support provider p95 | 45,000 ms | Extended shadow observation SLO |
| Provider timeout and collection stop | 60,000 ms | Hard request and evidence-collection upper bound |

Completing within the provider timeout does not imply that either latency SLO
was met. The 45-second SLO is assessed after terminal evidence collection and
is not reused as a request timeout.

The current `PermissionFilteredHybridPackageRuntime` invokes an installed
shadow observer synchronously before returning the primary package. That shape
is incompatible with the 8-second interactive objective for a provider whose
observed p95 is approximately 40 seconds. Therefore:

- synchronous inline provider execution is prohibited;
- asynchronous isolation is required before activation;
- shadow failure or delay must not alter the primary package;
- a later operator decision is required after async runtime acceptance;
- production cutover remains prohibited.

## Implementation

The Slice adds:

- a pre-observation SLO design bound to the P-U decision, readiness manifest,
  runtime profile, provider binding, policy, and case-set hashes;
- 30 unique public-synthetic cases with no HOLDOUT reuse;
- a bounded one-shot policy with one request at a time, zero provider-failure
  allowance, a 60-second timeout/stop budget, and no user visibility;
- a product contract that validates immutable evidence and evaluates the
  45-second background SLO without making provider or database calls;
- a protected runner that reuses the P-T canary engine, records mode-`0600`
  terminal receipts, and preserves disabled-smoke terminal evidence;
- fail-closed contract, binding, sample-count, latency, and one-shot checks.

The SLO evaluator records both `MET` and `MISSED` outcomes as terminal
observations. A miss prohibits cutover but does not discard valid measurement
evidence.

## Protected Live Evidence

The admitted provider binding remained unchanged:

```text
served model       = Qwen3.5-9B
deployment         = dgx-qwen3-5-9b-9116
model revision     = hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a
provider port      = 9116
```

Observed result:

```text
completed samples       = 30
provider failures       = 0
latency samples         = 30
p95 latency             = 40,241.896 ms
maximum latency         = 40,560.030 ms
background p95 SLO      = MET (<= 45,000 ms)
disagreements           = 3 / 30 (10.0%, observation only)
total tokens            = 13,951
database calls          = 0
HOLDOUT accessed        = false
runtime activation      = prohibited
production cutover      = prohibited
```

Evidence binding:

```text
design hash             = sha256:9cf3a234bea295b7f46d8accd6d244a11f39060eae4a0665227919b7e83d99d5
extended receipt hash   = sha256:f9c500c947714c0c2bee6a367c6c1fd7823a47dbab34b322f255d7f02bbae13b
SLO manifest hash       = sha256:8101f36d66a22ad7b225c53132494286af06bcef4d6bfa04a1a96c5342c72a57
SLO receipt hash        = sha256:97815dd4111632e6628d40553e7dbc1016d3bed802773054f262c6f8c6aecfd1
```

An initial invocation was interrupted by the execution tool's five-minute
session boundary and left only a `RUNNING` reservation. It was quarantined as
an aborted, non-terminal receipt and excluded from all metrics and decisions.
The admitted observation was then rerun in a continuously polled long-running
session and completed normally.

## Verification

Focused regression:

```text
39 passed
new product contract statement/branch = 100% / 100%
new protected runner statement/branch = 100% / 100%
```

NeX-CX Slice Gate:

```text
tests                         = 3,049 passed
statement coverage            = 99.17%
branch coverage               = 98.41%
new product contract coverage = 100% statement / 100% branch
new protected runner coverage = 100% statement / 100% branch
contract validation           = 230 schemas, 291 examples,
                                245 negative examples, 10 OpenAPI documents
golden transition audit       = pass
demo dependency audit         = pass
tiered Slice Gate             = 7/7 commands passed
```

The gate's default-disabled smoke invocation returned `SKIPPED` and did not
overwrite the terminal live evidence.

## Next Boundary

`ASYNC_SHADOW_EXECUTION_AND_CAPACITY_HARDENING`

The next boundary must isolate answer-support shadow calls from the interactive
retrieval request, define queue/backpressure and restart behavior, preserve the
current policy as fallback, and measure user-path overhead. Only after that
acceptance may a new operator decision consider limited runtime activation.
