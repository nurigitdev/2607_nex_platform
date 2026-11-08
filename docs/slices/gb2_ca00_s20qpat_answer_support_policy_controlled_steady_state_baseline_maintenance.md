# GB2-CA00-S20Q-P-AT: Answer-Support Policy Controlled Steady-State Baseline Maintenance

## Outcome

Status: `PASS`

Decision:

`ANSWER_SUPPORT_POLICY_CONTROLLED_STEADY_STATE_BASELINE_MAINTENANCE_ACTIVE`

The P-AS controlled-operations baseline is now governed by a passive
maintenance guardrail. This state does not open another corrective chain,
authorize production cutover, rerun HOLDOUT, or mutate the installed runtime.

## Maintenance Contract

The committed maintenance policy binds the exact P-AS closure design, closure
manifest, closure evidence document, continuation policy, operations profile,
and selected answer-support policy hashes.

The baseline remains admitted only while all bound identities remain exact.
Maintenance uses both of these review paths:

1. Event-driven review when a frozen reopen condition is observed.
2. Periodic operator review no later than 30 days after the last review.

Periodic review expiry does not automatically reopen the corrective chain. It
holds admission pending operator review. Identity drift or an admitted reopen
event also holds the baseline, but requires a separate explicit reopen
admission. Provider-backed revalidation is never started automatically.

## Frozen Reopen Conditions

1. Model or provider revision changed.
2. Request profile or score semantics changed.
3. Calibration dataset or selected policy changed.
4. Operations profile or SLO changed.
5. Permission or tenant boundary changed.
6. Fallback, restart, or rollback guarantee drifted.
7. An operator explicitly decided to reopen the baseline.

Unknown events, malformed hashes, policy tampering, closure evidence drift,
expired review windows, and future-dated review windows fail closed.

## Implementation

- Committed policy:
  `services/nex-cx/nex_cx/data/answer_support_policy_controlled_steady_state_baseline_maintenance.v1.json`
- CX validation and maintenance projection:
  `services/nex-cx/nex_cx/retrieval_answer_support_policy_controlled_steady_state_baseline_maintenance.py`
- Protected evidence runner:
  `scripts/smoke/run_gb2_s20qpat_answer_support_policy_controlled_steady_state_baseline_maintenance.py`
- Owner-private evidence:
  `reports/live/gb2_ca00_s20qpat_answer_support_policy_controlled_steady_state_baseline_maintenance.json`

No migration, API route, runtime wiring, Compose configuration, provider call,
database call, or HOLDOUT access was added.

## Protected Evidence

The protected run admitted the exact frozen baseline and recorded:

```text
maintenance status       = ACTIVE_CONTROLLED_BASELINE_MAINTENANCE
admission status         = ADMITTED_CONTROLLED_BASELINE
review due               = false
drifted fields           = 0
triggered reopen events  = 0
provider calls           = 0
database calls           = 0
runtime changed          = false
production cutover       = false
policy hash              = sha256:b91c6e1558f42491c71bdab7d8071bf049280d53510ff617ec17300e1125d146
maintenance hash         = sha256:e1a09694fb93b8b3d955bb7fb9e7ad6ebc949aeb3938e120e418fb64390b42ce
next review due          = 2026-12-06T12:07:19.102748Z
```

The evidence mode is `0600`. Its file SHA-256 is:

`738d6bea91de96b649af50bfec52723cb6717a36abe1587ed79745922c9987fb`

## Verification

```text
focused tests             = 18 passed
focused statement/branch  = 100% / 100%
answer-support regression = 933 passed
protected maintenance     = PASS

NeX-CX Slice Gate          = 3,382 passed
statement coverage         = 99.28%
branch coverage            = 98.51%
contract validation        = 230 schemas, 291 examples,
                             245 negative examples, 10 OpenAPI documents
golden transition audit    = PASS
dependency audit           = PASS
tiered Slice Gate          = 5/5 commands passed
```

## Next Operational Boundary

`ANSWER_SUPPORT_POLICY_CONTROLLED_STEADY_STATE_BASELINE_PERIODIC_REVIEW`

This is an operational cadence, not a mandatory corrective Slice. Until a
frozen trigger occurs or the review deadline is reached, the exact P-AS
baseline continues under controlled steady-state operation.
