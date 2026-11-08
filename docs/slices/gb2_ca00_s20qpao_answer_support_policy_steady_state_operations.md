# GB2-CA00-S20Q-P-AO Answer-Support Policy Steady-State Operations

## Outcome

`GB2-CA00-S20Q-P-AO` is complete. The accepted P-AN activation was operated
through one complete P-AL steady-state review cadence using the actual CX test
database and the admitted generation provider. The protected decision is:

```text
ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATIONS_ACCEPTED
```

This boundary does not rerun HOLDOUT, reselect calibration, change retrieval
ordering, alter the answer-support algorithm, or authorize platform production
release. Runtime remains active after the cadence while operator review becomes
due.

## Installed Boundary

The installed operations source binds the exact accepted activation and
operations profile before it can record or project a steady-state window:

```text
P-AN activation evidence  = sha256:f03487ff10b867e0b19c60933369c1dbc8e26c9c0c90b1972d7c14dbb506bcbc
steady-state authorization= sha256:082356e051209a0819886b48be5b8dadf41ef63991572b97ce5ede059cefd008
operations profile        = sha256:a7332978f9779253959c555bf9e4186ff59020363431d0962b9442d4712d5376
selected policy           = sha256:c81f7a0bf3d3d72d7bbc5de1f564ada3b415f2206689c1939fcb925f172168cb
operations policy         = sha256:5b758ee97e34d6a5fa1eca190ade25eaeb3f1f5bd451a8c6edd16296bdaaa76c
```

Canonical Compose explicitly supplies the admitted operations policy path.
The AG-facing route is protected by the existing CX operations authorization:

```text
/internal/v1/retrieval/answer-support/policy-steady-state-operations
```

## Persistence and Review Cadence

No migration or new table was added. Restart-safe operations windows reuse
`service_operational_events` with event type:

```text
cx.retrieval.answer_support_policy_steady_state_window
```

The admitted cadence is 12 provider-backed decisions in three bounded waves of
four concurrent requests. Completion produces `OPERATOR_REVIEW_DUE`; it does
not stop the runtime. Provider failure, fallback, SLO breach, or a terminal
cutover state still takes precedence and drives the existing rollback path.
Permission snapshots, evidence, candidate ordering, and the incumbent fallback
contract remain unchanged.

## Protected Live Acceptance

The protected runner used the actual `nex_cx_test` PostgreSQL database and the
admitted Qwen3.5-9B provider. It completed the operations cadence, reconstructed
state after restart, injected a provider failure, and verified rollback
dominance and zero residue.

```text
sample count             = 12
provider calls           = 12
ready / low confidence   = 9 / 3
maximum concurrency      = 4
peak in flight           = 4
feedback p95             = 0.586509 ms
provider p95             = 11,128.926590 ms
end-to-end p95           = 11,154.375 ms
elapsed wall time        = 33.220090 s
operations status        = OPERATOR_REVIEW_DUE
runtime stopped          = false
restart recovery         = PASS
forced rollback          = PASS / ROLLED_BACK
test DB residue          = 0 rows
```

The resulting `health_status=ATTENTION` represents the due operator review,
not a failed health or SLO check. All 22 acceptance checks passed. The evidence
file is mode `0600` and contains no endpoint, API key, or database credential:

```text
reports/live/gb2_ca00_s20qpao_answer_support_policy_steady_state_operations.json
evidence hash = sha256:ba6ac667e2065e1a2b16019529db164d4f8824131aea6a9db5b8cc6eaa3602a0
```

## Verification

```text
focused product tests      = 10 passed
focused product and runner = 15 passed
new product module         = 100% statement / 100% branch
answer-support regression  = 652 passed
canonical deployment tests = 109 passed
protected live acceptance  = PASS

NeX-CX Slice Gate           = 3,301 passed
statement coverage          = 99.27%
branch coverage             = 98.48%
contract validation         = 230 schemas, 291 examples,
                              245 negative examples, 10 OpenAPI documents
golden transition audit     = PASS
dependency audit            = PASS
tiered Slice Gate           = 5/5 commands passed
```

## Next Boundary

`ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATIONS_OPERATOR_REVIEW`

The next boundary may review this exact operations evidence and decide whether
steady-state operation should continue, remain under observation, or roll back.
It must not rerun HOLDOUT, infer production-release approval, or weaken rollback
dominance, permission isolation, evidence integrity, and the admitted SLOs.
