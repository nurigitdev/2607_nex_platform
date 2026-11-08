# GB2-CA00-S20Q-P-Z Runtime Activation Operator Decision

## Outcome

`GB2-CA00-S20Q-P-Z` is complete. The Slice consumes the immutable P-Y
idle-confirmed PASS evidence and records this explicit operator decision:

```text
CONTROLLED_SYNCHRONOUS_SHADOW_ACTIVATION_APPROVED
```

The approval is limited to the bounded synchronous answer-support shadow
observer. Its status is `APPROVED_NOT_ACTIVATED`: this Slice authorizes the
next installed-composition boundary but does not change startup wiring,
activate a process, alter the user-visible READY decision, or approve
production cutover.

## Approved Boundary

```text
approved scope       = BOUNDED_SYNCHRONOUS_ANSWER_SUPPORT_SHADOW_OBSERVER
execution mode       = SYNCHRONOUS
maximum in flight    = 4
admission strategy   = BOUNDED_SEMAPHORE
overload behavior    = retryable rejection or deferral
request timeout      = 60 seconds
reasoning mode       = disabled
current policy       = CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY
fallback/rollback    = CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY
user-visible change  = prohibited
production cutover   = prohibited
```

`runtime_activation_permitted=true` in the decision manifest means that the
operator approved this exact scope for the next Slice. The same manifest and
receipt explicitly retain `runtime_activated=false`.

## Source Evidence

The decision binds the exact controlled P-Y retry, not the earlier busy-state
rejection:

```text
P-Y design hash        = sha256:4e99897710d2de8076159dce62eb24380a66f5583e927b23d900d9a9a9f5f758
P-Y receipt hash       = sha256:d78adfaf26a67263a7f22ed8037e6cae6236158ae90b0f1ca93b1cb7c18b864a
P-Y manifest hash      = sha256:89eaf18d0ff92b16ba1ff9691ce4e781e0a5be9bb1a0f08fba0330e12c7381c6
selected policy hash   = sha256:c81f7a0bf3d3d72d7bbc5de1f564ada3b415f2206689c1939fcb925f172168cb
accepted samples       = 30
peak in flight         = 4
provider errors        = 0
progress failures      = 0
feedback p95           = 0.919037 ms
provider p95           = 11,070.147572 ms
end-to-end p95         = 11,071.325844 ms
```

Receipt, report, E2E design, selected policy, readiness manifest, runtime
profile, and immutable provider binding are all verified. Hash or semantic
drift fails closed before an approval can be built.

## Rollback Policy

Immediate rollback is required for:

- source or provider binding drift;
- any provider error;
- any progress sink failure; and
- non-retryable overload behavior.

Feedback, provider, or end-to-end p95 SLO breach requires rollback pending
operator review. All rollback paths target the existing active retrieval
confidence policy.

## Protected Decision Evidence

The protected one-shot execution made no provider, database, or HOLDOUT call.
It produced:

```text
design hash            = sha256:297a9af1b471e43d84721b7e0a747f5a07a3335612d8cd781a8caf772a2ce479
operator decision hash = sha256:4eb6b8951e25a69cdc59c81b27be13d5b492e0dbb5327c901d58986002c0caa2
manifest hash          = sha256:b124a623be130bed54abe225f724a508db43e45ff7d3bb921c79718fd0751f1e
decision receipt hash  = sha256:7cff54fcae3f2413128f3e289b57062133a6fd72fbdfed1ea4eb5931aa5f8191
receipt mode           = 0600
provider calls         = 0
database calls         = 0
HOLDOUT accessed       = false
runtime approved       = true
runtime activated      = false
production cutover     = false
```

The ignored local evidence files are:

- `reports/live/gb2_ca00_s20qpz_runtime_activation_operator_decision.json`;
- `reports/live/gb2_ca00_s20qpz_runtime_activation_operator_decision_receipt.json`.

## Verification

Focused verification:

```text
tests                    = 15 passed
product decision module  = 99.23% statement / 96.88% branch
protected runner         = 100% statement / 100% branch
format and lint          = pass
```

Final Slice Gate:

```text
NeX-CX regression        = 3,119 passed
statement coverage       = 99.19%
branch coverage          = 98.44%
product decision module  = 99.23% statement / 96.88% branch
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

`CONTROLLED_RUNTIME_ACTIVATION_AND_ROLLBACK_ACCEPTANCE`

The next Slice may wire the approved observer into the installed CX runtime
composition behind explicit configuration, verify startup/restart behavior,
exercise immediate rollback conditions, and perform a bounded live acceptance.
It must keep the current retrieval confidence policy authoritative and must
not infer production cutover from this approval.
