# GB2-CA00-S20Q-P-W Synchronous Concurrency and Capacity Characterization

## Outcome

`GB2-CA00-S20Q-P-W` and its operator-requested trailing c1 control are
complete. The admitted Qwen3.5-9B generation provider was measured with
synchronous concurrency profiles 1, 2, and 4 using the same 30
public-synthetic cases and immutable provider binding.

The terminal observation is:

```text
SYNCHRONOUS_BACKGROUND_CANDIDATE_OPERATOR_REVIEW_REQUIRED
ORIGINAL_C1_TEMPORAL_CONFOUND_LIKELY
```

The result does not select synchronous or asynchronous execution, activate a
runtime policy, or authorize production cutover. It corrects the earlier
assumption that the approximately 40-second c1 observation represented stable
single-request latency.

## Frozen Boundary

The Slice binds all observations to:

```text
served model       = Qwen3.5-9B
deployment         = dgx-qwen3-5-9b-9116
model revision     = hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a
provider port      = 9116
request timeout    = 60 seconds
sample count       = 30 per profile
HOLDOUT access     = prohibited
database calls     = prohibited
```

The operator-declared vLLM `max-num-seqs=4` value is recorded as an operator
observation. Ports 9112, 9113, and 9116 were reachable during both evidence
runs, but endpoint reachability is only a co-resident-provider proxy. It is
not GPU utilization, queue-depth, or absence-of-load attestation.

The first run reused the preceding P-V c1 receipt and executed c2 and c4. The
large difference from that older c1 measurement could not safely be
attributed to concurrency because the measurements were taken at different
times. A separate fail-closed P-W-A control therefore required explicit
operator confirmation that no known competing vLLM request was active, then
executed a new trailing c1 sample without changing the P-W receipt.

## Live Evidence

| Profile | p95 latency | Maximum latency | Elapsed | Throughput | Errors |
| --- | ---: | ---: | ---: | ---: | ---: |
| Original c1, P-V receipt | 40,241.896 ms | 40,560.030 ms | 841.875 s | 0.035635 req/s | 0 |
| c2, P-W live | 10,457.676 ms | 10,669.050 ms | 151.658 s | 0.197813 req/s | 0 |
| c4, P-W live | 10,967.550 ms | 11,010.584 ms | 82.787 s | 0.362375 req/s | 0 |
| Trailing c1, P-W-A live | 10,927.853 ms | 11,076.376 ms | 315.387 s | 0.095121 req/s | 0 |

The new c1 p95 was:

- `1.045x` the c2 p95;
- `0.996x` the c4 p95;
- `0.272x` the original P-V c1 p95.

Using the new c1 as the comparison control, c2 delivered `2.080x` throughput
and c4 delivered `3.810x` throughput while keeping per-request p95 in the same
approximately 11-second band. All profiles met the 45-second background SLO
and 60-second timeout bound. None met the existing 8-second interactive
end-to-end objective.

This sequential observation supports the conclusion that the original
40-second result was likely affected by temporal provider state or competing
load. It does not prove a causal concurrency effect because the profiles were
not randomized or executed under machine-attested identical GPU conditions.

Evidence binding:

```text
P-W design hash        = sha256:50868cb1551070bc6622cf82008a5c23384671235019473578b342014d93b75e
P-W receipt hash       = sha256:a2ca5bec7621626e97013cddd7e913cc145bdb2b72c5ffcbb0b3f9928d5c541e
P-W manifest hash      = sha256:378933b6c030c408b774c5bc44291717f66bdc2117c7ec4363b68bf42271160e
P-W-A design hash      = sha256:91710cadebc3aef40e533f80b48e3a5d53cd92d6aeb5cf4e3edfc20986955b55
P-W-A receipt hash     = sha256:867ba89267b1f7a3fa1d45eb0fcee43bdaad053b6da3d1f8c56c159cf28272f6
P-W-A manifest hash    = sha256:d456991f604f91c40b939de0cfb9292c6d88306008809839236017358c2db05d
```

## Implementation

The Slice adds:

- a frozen c1/c2/c4 synchronous capacity contract;
- strict immutable provider, model revision, case, signal, and request-profile
  bindings;
- bounded request budgets and mode-`0600` one-shot receipts;
- co-resident endpoint reachability observation;
- aggregate latency, throughput, token, and error metrics without query or
  candidate persistence;
- a separate c1 control requiring explicit DGX-idle operator confirmation;
- deterministic comparison classifications that cannot select execution mode
  or alter the active retrieval policy.

Default-disabled smoke execution preserves terminal live evidence and does not
consume the one-shot boundary.

## Verification

The initial P-W Slice Gate completed before the trailing control was added:

```text
tests                    = 3,073 passed
statement coverage       = 99.18%
branch coverage          = 98.41%
P-W product contract     = 100% statement / 100% branch
P-W protected runner     = 99.60% statement / 98.39% branch
contract validation      = 230 schemas, 291 examples,
                           245 negative examples, 10 OpenAPI documents
tiered Slice Gate        = 7/7 commands passed
```

The final combined verification completed after the live c1 control:

```text
focused P-W/P-W-A regression      = 55 passed
repository NeX-CX regression      = 3,093 passed
statement coverage                = 99.19%
branch coverage                   = 98.43%
P-W-A product contract            = 100% statement / 100% branch
P-W-A protected runner            = 100% statement / 100% branch
contract validation               = 230 schemas, 291 examples,
                                    245 negative examples, 10 OpenAPI documents
golden transition audit           = pass
demo dependency audit             = pass
tiered Slice Gate                 = 8/8 commands passed
```

Both default-disabled smoke invocations returned `SKIPPED` and preserved the
terminal live evidence.

## Next Boundary

`SYNCHRONOUS_CAPACITY_OPERATOR_INTERPRETATION`

The next operator decision should treat synchronous concurrency 4 as a
capacity candidate, retain the 60-second timeout and bounded queue/backpressure
requirements, and keep the 8-second interactive objective distinct from the
45-second background provider SLO. A model-size change or asynchronous
isolation remains an explicit later decision rather than an automatic outcome
of this Slice.
