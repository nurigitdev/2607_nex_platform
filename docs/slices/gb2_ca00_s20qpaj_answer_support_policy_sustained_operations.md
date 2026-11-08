# GB2-CA00-S20Q-P-AJ Answer-Support Policy Sustained Operations

## Outcome

`GB2-CA00-S20Q-P-AJ` is complete. The controlled answer-support policy now
has a restart-safe sustained-operations projection, a protected AG-facing
read model, and an explicit twelve-decision operator-review cadence.

Reaching the cadence does not stop the authoritative runtime. It changes the
operations projection to `OPERATOR_REVIEW_DUE` while the P-AG rollback
contract remains dominant. HOLDOUT access and production release
authorization remain prohibited.

## Immutable Policy Boundary

The installed policy is:

```text
services/nex-cx/nex_cx/data/answer_support_policy_sustained_operations.v1.json
```

Its immutable lineage is:

```text
sustained policy hash      = sha256:4524e2e54929f42fe1c2e60b6c93941a373a0359ead5810126045c3668c99f6a
P-AI decision receipt hash = sha256:36c97a3f3033d8963edea0931f05378799e2dfd273bb12cb65599ccaf5899ade
P-AI operator decision     = sha256:5a4285d0b75fe10676ae00a43ab8c41016bcb8db61ec911e8ba947b467b87843
authorization hash         = sha256:fe45b9267af3e81095b957c0488ee86dba7f88114b3fff99708ccc812108fc00
activation bundle hash     = sha256:6d5c631c9e18418ae2787d4053d06cdf87cc49a3cbc67aea6258b11f29893a06
selected policy hash       = sha256:c81f7a0bf3d3d72d7bbc5de1f564ada3b415f2206689c1939fcb925f172168cb
```

The policy admits at most concurrency four and requires operator review after
every twelve provider-backed decisions. Its SLOs are provider p95 at or below
15 seconds, end-to-end p95 at or below 20 seconds, feedback p95 at or below
2 seconds, and zero provider failures or fallback decisions.

## Runtime and Escalation

No migration or new table was added. The implementation reuses
`service_operational_events` and adds the deterministic window marker:

```text
cx.retrieval.answer_support_policy_sustained_window
```

The existing decision, progress, and terminal cutover events remain the
authoritative inputs. Escalation ordering is fail-closed:

```text
terminal cutover state       -> terminal state remains dominant
provider failure or fallback -> immediate rollback required
provider or E2E SLO breach   -> rollback pending operator review
twelve decisions observed    -> operator review required
otherwise                    -> controlled monitoring continues
```

The protected read-only route is:

```text
GET /internal/v1/retrieval/answer-support/policy-sustained-operations
```

It uses the existing CX operations authorization boundary and does not expose
query, candidate, prompt, or provider-secret material.

## Protected Live Acceptance

The protected runner used the actual `nex_cx_test` PostgreSQL database and the
immutable Qwen3.5-9B provider profile. It made twelve generation requests in
three concurrency-four waves.

```text
sample count                = 12
provider calls              = 12
peak in-flight              = 4
READY decisions             = 9
LOW_CONFIDENCE decisions    = 3
feedback p95                = 0.633351 ms
provider p95                = 11,025.55996 ms
end-to-end p95              = 11,048.494 ms
elapsed wall time           = 32.941331 s
restart recovery            = PASS
runtime stopped at cadence  = false
operations status           = OPERATOR_REVIEW_DUE
test DB residue             = 0 rows
```

All sustained-operations checks passed. The ignored local evidence is:

```text
reports/live/gb2_ca00_s20qpaj_answer_support_policy_sustained_operations.json
semantic evidence hash = sha256:dd021190d164c1b0eb1a66af09cd8d8169b5926500cc75d1e1d547c7f78889a8
file SHA-256          = 0af26b292456c400995489d8c0deaece21df459cfdafa8585f57a1c7153ae93d
```

## Verification

```text
focused tests              = 27 passed
focused module and runner  = 100% statement / 100% branch
P-AH/P-AI adjacent tests   = 71 passed
canonical deployment tests = 63 passed
canonical Compose audit    = PASS

NeX-CX Slice Gate          = 3,223 passed
statement coverage         = 99.24%
branch coverage            = 98.44%
contract validation        = 230 schemas, 291 examples,
                             245 negative examples, 10 OpenAPI documents
golden transition audit    = PASS
dependency audit           = PASS
tiered Slice Gate          = 5/5 commands passed
```

## Next Boundary

`ANSWER_SUPPORT_POLICY_SUSTAINED_OPERATIONS_OPERATOR_REVIEW`

The next boundary may review this exact sustained-operations evidence and
decide whether controlled operation should continue. It must not rerun
HOLDOUT, infer production release authorization, or weaken the existing
rollback contract.
