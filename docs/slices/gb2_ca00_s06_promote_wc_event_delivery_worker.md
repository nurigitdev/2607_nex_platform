# GB2-CA00-S06: Promote WC Event-Delivery Worker

## Scope

S06 promotes the NeX-WC event-delivery worker from the P8-DEMO installed
composition into a first-class current Platform process. The promoted process
uses service-owned source and does not import `nex_wc.demo_runtime`, shared demo
process source, or smoke-test source.

This Slice adds no database migration, table, queue model, event model, public
business API, or new delivery semantics.

## Canonical Process

```text
process_id       = nex-wc-event-delivery-worker
artifact_id      = nex-wc-runtime
module           = nex_wc.event_delivery_process
capability       = event_delivering
database         = NeX-WC PostgreSQL
heartbeat        = service_worker_heartbeats
shutdown         = SIGINT / SIGTERM graceful stop
```

The process reuses the existing service-local `SqlAlchemyJobQueue`, WC
coordination and WorkResult repositories, approval event outbox, signed AE
transport clients, retry settlement, and worker heartbeat. It serves three
existing delivery paths:

```text
CLAIM_HANDOFF
WORK_RESULT
APPROVAL_EVENT
```

`local_mock` remains package/source admission only. Durable delivery work is
allowed only through the protected `test` profile in this Slice.

## Readiness And Recovery

Readiness fails closed unless the WC database is reachable, the exact migration
inventory is current, all required queue/outbox/coordination tables exist, the
three delivery paths are assembled, and signed AE transport is configured.

The worker bridges pending handoff and WorkResult outbox rows into the existing
`WC_EVENT_DELIVERY` queue, claims one durable job, settles it through the common
worker runner, and then drains the existing approval outbox. Restart reconstructs
the same adapters from PostgreSQL. Pending or retryable work remains durable;
completed work is replay-idempotent.

## Deployment Reconciliation

The current process manifest, deployment artifact binding, and packaged
entrypoint catalog now include the WC worker. The current topology is therefore
`9 artifacts / 19 installed processes`; the GB2 target remains `9 / 20` after
the EOS outbox-publisher promotion.

The S01 inventory now records:

```text
promotion targets       = 3
currently promoted      = nex-ae-agent-runtime-worker
                          nex-wc-event-delivery-worker
remaining promotions    = 1
target process count    = 20
```

## Protected Component Evidence

The opt-in S06 smoke applies the current WC and AE migrations to the actual
`nex_wc_test` and `nex_ae_test` databases and verifies their exact database and
role identities. It creates a legitimate pending WC handoff through the owning
domain service, then proves:

```text
wrong but valid signed caller is rejected with 403
retryable failure returns the durable queue job to retry
process reconstruction resumes and delivers the pending event
WC delivery result is persisted
AE execution and inbox rows are admitted exactly once
completed-job replay is idempotent
subsequent restart does not double-deliver
worker heartbeat is persisted
component-owned cleanup leaves zero residue
```

Evidence classification is `PROTECTED_COMPONENT`. Remote embedding, reranking,
and generation providers are not needed for S06.

## Coverage Note

The generic WC service-only Gate still includes historical demo source and older
coordination/result persistence branches whose whole-service baseline predates
GB2 and remains below the repository default `95% / 94%` thresholds. S06 does
not lower those thresholds or represent that baseline as a pass. The two
S06-owned modules are covered at `100%` statement and branch coverage, and the
stronger Repository Checkpoint Gate is the closure authority for this Slice.

## Verification

```text
focused S06 tests                         = 50 passed
S06-owned statements / branches          = 345 / 68, all covered
S06-owned statement / branch coverage    = 100.00% / 100.00%
Repository Checkpoint Gate               = 17,663 passed, 123 skipped
Repository statement / branch coverage   = 98.35% / 96.80%
contract validation                      = 226 / 290 / 244 / 10
actual PostgreSQL component checks       = 13 / 13
durable delivery jobs / AE HTTP attempts = 1 / 3
remaining component rows                 = 0
ruff / diff check                        = PASS
```

The initial WC service-only Gate exposed the pre-existing whole-service coverage
baseline rather than a behavior failure. No threshold was weakened for closure;
the complete Checkpoint Gate and actual PostgreSQL smoke were run and passed.

## Exit

```text
WC event-delivery worker     = CURRENT PLATFORM PROCESS
existing queue/event reuse   = PASS
demo runtime dependency      = NONE
wrong signed trust           = FAIL-CLOSED
restart / idempotent replay  = PASS
protected PostgreSQL smoke   = PASS
database migration           = NONE
Repository Checkpoint Gate   = PASS
next slice                   = GB2-CA00-S07
```
