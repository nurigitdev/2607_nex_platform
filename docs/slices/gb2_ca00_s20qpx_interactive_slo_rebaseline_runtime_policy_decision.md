# GB2-CA00-S20Q-P-X Interactive Latency SLO Rebaseline and Synchronous Runtime Policy Decision

## Outcome

`GB2-CA00-S20Q-P-X` is complete. The Slice rebaselines the interactive
latency objectives and selects the bounded synchronous c4 profile as the
runtime candidate:

```text
SYNCHRONOUS_BOUNDED_C4_SELECTED_PENDING_E2E_ACCEPTANCE
```

This is a versioned policy selection, not runtime activation or production
cutover. The preceding P-W and P-W-A receipts remain immutable. In particular,
the earlier 8-second objective and its evidence were not rewritten.

## Rebaselined SLO

| Boundary | p95 objective |
| --- | ---: |
| Prompt acceptance or progress feedback | 2,000 ms |
| Generation provider | 15,000 ms |
| Final interactive response end-to-end | 20,000 ms |
| Background provider | 45,000 ms |
| Hard request timeout | 60,000 ms |

The approximately 11-second provider latency measured for Qwen3.5-9B makes the
old 8-second end-to-end objective physically inconsistent with the admitted
provider profile. The 20-second final-response objective leaves a bounded
budget for admission, prompt assembly, transport, persistence, verification,
and publication while preserving the existing 60-second hard timeout.

The 2-second objective concerns request acceptance or visible progress. It
does not require generation completion within 2 seconds.

## Selected Runtime Policy

```text
execution mode                 = SYNCHRONOUS
maximum in-flight requests     = 4
admission strategy             = BOUNDED_SEMAPHORE
overload behavior              = DEFER_OR_REJECT_RETRYABLE
generation request timeout     = 60 seconds
reasoning mode                 = DISABLED
selection status               = SELECTED_PENDING_E2E_ACCEPTANCE
```

The c4 value is the provider-wide maximum in-flight request candidate. It is
not four provider calls per user request. A bounded admission mechanism is
required before activation so excess work cannot create an unbounded queue.

The fresh P-W/P-W-A profiles used by the decision were:

| Concurrency | p95 latency | Maximum latency | Throughput | Errors |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 10,927.853 ms | 11,076.376 ms | 0.095121 req/s | 0 |
| 2 | 10,457.676 ms | 10,669.050 ms | 0.197813 req/s | 0 |
| 4 | 10,967.550 ms | 11,010.584 ms | 0.362375 req/s | 0 |

All three fresh profiles met the 15-second provider objective with zero
errors. The c4 profile had the highest observed throughput. The original
approximately 40-second c1 sample is excluded from selection because P-W-A
classified it as a likely temporal or provider-state confound.

## Safety Boundary

The protected decision runner made no provider or database calls and did not
access HOLDOUT data. Its one-shot receipt is mode `0600`.

Activation remains prohibited until all three pending items are accepted:

1. prompt acceptance or progress-feedback p95 measurement;
2. final interactive response end-to-end p95 measurement;
3. bounded in-flight admission wiring in the installed runtime.

The current active retrieval-confidence policy remains the fallback. A model
revision change invalidates the supporting provider binding and requires a new
capacity and latency decision.

## Evidence

```text
design hash             = sha256:d0051b32f0c0aac96e6b8c377af4bcc6d5db850b3da1d9f97f0edb765de5d11a
selected policy hash    = sha256:c81f7a0bf3d3d72d7bbc5de1f564ada3b415f2206689c1939fcb925f172168cb
manifest hash           = sha256:038d6a9ec2c6a468d22050a8acb8075caf71e7583db0a8f22a69220f4b33a78b
decision receipt hash   = sha256:3f5399ee9966503aa73fa94ea9653c6b7e65ac11fe0f312f174b04d6cd905d90
receipt mode            = 0600
provider calls          = 0
database calls          = 0
HOLDOUT accessed        = false
runtime activated       = false
production cutover      = false
```

Focused P-X verification:

```text
tests                    = 19 passed
product policy contract  = 100% statement / 100% branch
protected runner         = 100% statement / 100% branch
```

Final Slice Gate:

```text
NeX-CX regression        = 3,107 passed
statement coverage       = 99.19%
branch coverage          = 98.44%
product policy contract  = 100% statement / 100% branch
protected runner         = 100% statement / 100% branch
contract validation      = 230 schemas, 291 examples,
                           245 negative examples, 10 OpenAPI documents
golden transition audit  = pass
dependency audit         = pass
tiered Slice Gate        = 7/7 commands passed
```

The default-disabled smoke invocation returned `SKIPPED` and preserved the
terminal one-shot decision evidence.

## Next Boundary

`SYNCHRONOUS_RUNTIME_E2E_ACCEPTANCE`

The next Slice should wire bounded c4 admission in the installed runtime and
measure the 2-second feedback and 20-second final-response objectives without
re-running or modifying this operator decision receipt.
