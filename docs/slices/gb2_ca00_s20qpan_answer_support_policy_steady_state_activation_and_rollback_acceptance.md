# GB2-CA00-S20Q-P-AN Answer-Support Policy Steady-State Activation and Rollback Acceptance

## Outcome

`GB2-CA00-S20Q-P-AN` is complete. The P-AM operator authorization and exact
P-AL operations profile were installed as a controlled wrapper around the
existing answer-support policy cutover runtime. The protected acceptance
decision is:

```text
ANSWER_SUPPORT_POLICY_STEADY_STATE_ACTIVATION_AND_ROLLBACK_ACCEPTED
```

This boundary activates controlled steady-state operations. It does not rerun
HOLDOUT, reselect a calibration profile, change retrieval ordering, mutate the
answer-support algorithm, or authorize platform production release.

## Installed Boundary

The installed runtime verifies the immutable P-AM/P-AL lineage before it can
be selected as the CX primary answer-support policy:

```text
steady-state authorization = sha256:082356e051209a0819886b48be5b8dadf41ef63991572b97ce5ede059cefd008
P-AM decision receipt      = sha256:4d3277da3c9e6591cdc176fb3a062b1ff1c72efed40b7f3e9c3ffcb4b199b2b6
operations profile         = sha256:a7332978f9779253959c555bf9e4186ff59020363431d0962b9442d4712d5376
cutover authorization      = sha256:fe45b9267af3e81095b957c0488ee86dba7f88114b3fff99708ccc812108fc00
activation bundle          = sha256:6d5c631c9e18418ae2787d4053d06cdf87cc49a3cbc67aea6258b11f29893a06
selected policy            = sha256:c81f7a0bf3d3d72d7bbc5de1f564ada3b415f2206689c1939fcb925f172168cb
sustained policy           = sha256:4524e2e54929f42fe1c2e60b6c93941a373a0359ead5810126045c3668c99f6a
```

The default remains fail-closed `DISABLED`. Canonical Compose explicitly sets
`NEX_CX_ANSWER_SUPPORT_STEADY_STATE_MODE=CONTROLLED` and provides the admitted
authorization document. Unknown modes, missing cutover delegates, altered
hashes, stale receipts, profile drift, and restored-state drift are rejected.

## Persistence and Rollback

No migration or new table was added. Restart-safe state reuses
`service_operational_events` with event type:

```text
cx.retrieval.answer_support_policy_steady_state
```

The wrapper records deterministic `ACTIVE`, `ROLLED_BACK`, and
`ROLLBACK_PENDING_REVIEW` events. Persisted binding fields use the names
`steady_state_receipt_hash` and `cutover_receipt_hash` so the generic
operational-event secret redactor does not mask their non-secret lineage
values.

The existing cutover runtime remains authoritative. Its terminal rollback
state always dominates the steady-state wrapper. A provider failure returns
the incumbent retrieval package, persists `PROVIDER_ERROR`, and remains
rolled back after process reconstruction. Permission snapshots, evidence
items, candidate ordering, and the existing fallback contract are preserved.

## Protected Live Acceptance

The protected runner used the actual `nex_cx_test` PostgreSQL database and the
admitted Qwen3.5-9B provider on DGX port 9116. It executed four concurrent
provider calls and then injected a provider failure to exercise rollback.

```text
sample count              = 4
provider calls            = 4
maximum concurrency       = 4
peak in flight            = 4
provider p95              = 10,968.525783 ms
end-to-end p95            = 11,021.340 ms
elapsed wall time         = 11.034299 s
active restart recovery   = PASS
forced provider rollback  = PASS / PROVIDER_ERROR
rollback restart fallback = PASS
permission preservation   = PASS
evidence preservation     = PASS
test DB residue           = 0 rows
```

The evidence file contains no endpoint, API key, or database credential and
is mode `0600`:

```text
reports/live/gb2_ca00_s20qpan_answer_support_policy_steady_state_activation.json
evidence hash = sha256:f03487ff10b867e0b19c60933369c1dbc8e26c9c0c90b1972d7c14dbb506bcbc
```

## Verification

```text
focused tests              = 14 passed
focused module and runner  = 98% combined
steady-state product module= 100% statement / 100% branch
answer-support regression  = 636 passed before final snapshot refactoring
canonical deployment tests = 109 passed
protected live acceptance  = PASS

NeX-CX Slice Gate          = 3,291 passed
statement coverage         = 99.26%
branch coverage            = 98.47%
contract validation        = 230 schemas, 291 examples,
                             245 negative examples, 10 OpenAPI documents
golden transition audit    = PASS
dependency audit           = PASS
tiered Slice Gate          = 5/5 commands passed
```

The final snapshot refactoring makes each wrapper snapshot read its delegate
exactly once. The final Slice Gate includes that regression test.

## Next Boundary

`ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATIONS`

The next boundary may operate and observe the accepted steady-state profile.
It must preserve the immutable policy/profile bindings, rollback dominance,
permission and evidence semantics, current SLOs, and the prohibition on
inferring platform production-release authorization from this acceptance.
