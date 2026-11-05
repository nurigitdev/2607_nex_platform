# GB2-CA00-S20Q-P-Y Synchronous Runtime E2E Acceptance

## Outcome

`GB2-CA00-S20Q-P-Y` is complete. The Slice wires and verifies the bounded
synchronous c4 runtime candidate selected by P-X. A controlled retry performed
after explicit operator confirmation that no known competing DGX request was
active passed all frozen acceptance checks:

```text
SYNCHRONOUS_RUNTIME_E2E_ACCEPTED_PENDING_OPERATOR_ACTIVATION
```

This acceptance does not activate the runtime policy or authorize production
cutover. The next boundary remains a separate operator decision.

## Runtime Boundary

The installed composition uses the existing answer-support shadow runtime and
adds a bounded, non-blocking admission layer:

```text
execution mode                 = SYNCHRONOUS
maximum in-flight requests     = 4
admission strategy             = BOUNDED_SEMAPHORE
overload behavior              = REJECT_RETRYABLE
generation request timeout     = 60 seconds
reasoning mode                 = DISABLED
```

Each accepted request emits admission and terminal progress events. Admission
feedback, provider execution, and final end-to-end latency are measured
separately. Capacity exhaustion is locally verified as a retryable rejection
without issuing an additional provider request.

## Acceptance Criteria

| Boundary | Frozen criterion | Controlled retry |
| --- | ---: | ---: |
| Admission feedback p95 | <= 2,000 ms | 0.919 ms |
| Provider p95 | <= 15,000 ms | 11,070.148 ms |
| End-to-end p95 | <= 20,000 ms | 11,071.326 ms |
| Provider errors | 0 | 0 |
| Admission rejections during accepted run | 0 | 0 |
| Peak in-flight requests | 4 | 4 |

The runner used the same 30 public-synthetic cases, immutable Qwen3.5-9B
revision binding, selected policy hash, request profile, and signal design as
the preceding decision chain. It made no database calls and did not access
HOLDOUT data.

## Load-Sensitive Evidence

The first execution was preserved as terminal rejected evidence. The operator
subsequently identified a competing DGX request during that observation. It
had no provider errors, but provider and end-to-end latency exceeded the
frozen objectives:

| Observation | Provider p95 | End-to-end p95 | Elapsed | Result |
| --- | ---: | ---: | ---: | --- |
| Initial, competing load reported | 43,239.474 ms | 43,241.706 ms | 171.982 s | FAIL |
| Retry 1, operator idle confirmation | 11,070.148 ms | 11,071.326 ms | 87.479 s | PASS |

The retry did not change code, cases, concurrency, model revision, selected
policy, or SLO thresholds. This comparison demonstrates load sensitivity; it
does not claim machine-attested isolation or causal attribution to a specific
co-resident process.

## Evidence

```text
design hash                    = sha256:4e99897710d2de8076159dce62eb24380a66f5583e927b23d900d9a9a9f5f758
selected policy hash           = sha256:c81f7a0bf3d3d72d7bbc5de1f564ada3b415f2206689c1939fcb925f172168cb
initial manifest hash          = sha256:1e66bc8c34824b9a1804ed5142034f70ee38ae6532ac58e89bb278f1bc8945e8
initial receipt hash           = sha256:2773386471771e66ae0babcfbab15b00363fc997537c5ac62b4f4f350f4a726c
controlled retry manifest hash = sha256:89eaf18d0ff92b16ba1ff9691ce4e781e0a5be9bb1a0f08fba0330e12c7381c6
controlled retry receipt hash  = sha256:d78adfaf26a67263a7f22ed8037e6cae6236158ae90b0f1ca93b1cb7c18b864a
receipt mode                   = 0600
sample count                   = 30
provider calls                 = 30
progress events                = 60
database calls                 = 0
HOLDOUT accessed               = false
runtime activated              = false
production cutover             = false
```

Both evidence sets remain separate. The protected receipt files are mode
`0600`, and the default-disabled runner preserves terminal evidence.

## Verification

Focused P-Y verification:

```text
tests                    = 13 passed
product runtime module   = 100% statement / 100% branch
protected runner         = 97.80% statement / 94.74% branch
format and lint          = pass
```

Final Slice Gate:

```text
NeX-CX regression        = 3,104 passed
statement coverage       = 99.17%
branch coverage          = 98.42%
product runtime module   = 100% statement / 100% branch
protected runner         = 97.80% statement / 94.74% branch
contract validation      = 230 schemas, 291 examples,
                           245 negative examples, 10 OpenAPI documents
golden transition audit  = pass
dependency audit         = pass
tiered Slice Gate        = 7/7 commands passed
```

The default-disabled smoke invocation returned `SKIPPED` and preserved both
terminal live evidence sets. The concurrency test fixture explicitly
synchronizes its first c4 wave so coverage instrumentation cannot reduce the
observed peak through scheduler timing alone.

## Next Boundary

`RUNTIME_ACTIVATION_OPERATOR_DECISION`

The next Slice may decide whether to activate this admitted synchronous
profile. It must retain explicit rollback, load-sensitive observability, and
the existing current-policy fallback. This Slice itself performs no activation
or production cutover.
