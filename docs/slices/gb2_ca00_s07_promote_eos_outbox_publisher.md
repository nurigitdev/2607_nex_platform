# GB2-CA00-S07: Promote EOS Outbox Publisher

## Scope

S07 promotes EOS outbox publication from the P8-DEMO installed composition to
a first-class current Platform process. The canonical process uses
service-owned source and does not import `nex_eos.demo_runtime`, shared Demo
composition, or smoke-test source.

This Slice adds no migration, table, queue model, event model, public business
API, or publication semantic. It assembles and operates existing EOS and AE
contracts.

## Canonical Process

```text
process_id       = nex-eos-outbox-publisher
artifact_id      = nex-eos-runtime
module           = nex_eos.outbox_publisher_process
capability       = outbox_publishing
database         = NeX-EOS PostgreSQL
downstream       = signed NeX-AE internal event admission
heartbeat        = service_worker_heartbeats
shutdown         = SIGINT / SIGTERM graceful stop
```

The process reuses `SqlAlchemyEosOutboxPublisher`,
`HttpAeEosOutboxTransport`, the EOS transactional outbox, OA-signed service
token admission at AE, and the shared worker heartbeat implementation.
`local_mock` is package/source admission only; durable publication requires the
protected `test` profile.

## Readiness And Recovery

Readiness fails closed unless the EOS database is reachable, its exact
migration inventory is current, all business-operation/outbox/heartbeat tables
exist, and signed AE transport is configured. The worker publishes at most one
pending row per cycle and persists every failed or successful attempt in the
existing outbox row.

Restart reconstructs the publisher and transport from PostgreSQL. A denied or
temporarily unavailable downstream leaves the item `PENDING`; a later process
instance retries it without repeating the owning business mutation. Published
rows are no longer selected, and AE event admission is idempotent by event ID
and payload hash.

## Deployment Reconciliation

The current process manifest, deployment artifact binding, packaged entrypoint
catalog, S01 inventory, and S02 capability projection now include the EOS
publisher. The current topology is therefore the GB2 target of
`9 artifacts / 20 installed processes`, with all three promotion targets
current:

```text
nex-ae-agent-runtime-worker
nex-wc-event-delivery-worker
nex-eos-outbox-publisher
```

## Protected Component Evidence

The opt-in S07 smoke applies current EOS and AE migrations to the actual
`nex_eos_test` and `nex_ae_test` databases and verifies exact database/role
identities. It creates the outbox row through
`SqlAlchemyEosBusinessTransactionCoordinator`, not by direct fixture insert,
then proves:

```text
wrong but valid signed caller is rejected with HTTP 403
failed publication persists PENDING with attempt_count = 1
process reconstruction publishes the same row with attempt_count = 2
published result and timestamp are durable
AE accepts the event and replay without creating a duplicate
subsequent restart finds no publishable work
the owning business mutation ran exactly once
worker heartbeat is durable
component-owned cleanup leaves zero residue
```

Evidence classification is `PROTECTED_COMPONENT`. Remote embedding, reranking,
and generation providers are not used. This component evidence does not claim
Golden Journey continuity.

## Coverage Note

The S07 process module is covered at 100% statement and branch coverage. The
NeX-EOS service Gate also includes historical Demo and older HTTP route source;
its aggregate branch coverage remains close to the repository threshold. S07
does not weaken that threshold, and the next S08 topology closure remains the
authority for Repository Full Gate #1.

## Verification

```text
focused S07 and topology tests          = 47 passed
S07 process statements / branches       = 223 / 40, all covered
S07 process statement / branch coverage = 100.00% / 100.00%
NeX-EOS Slice Gate                      = 766 passed, 22 protected skips
NeX-EOS statement / branch coverage     = 95.65% / 94.01%
contract validation                     = 226 / 290 / 244 / 10
actual PostgreSQL component checks      = 13 / 13
EOS outbox / AE HTTP attempts           = 1 / 3
remaining component rows                = 0
ruff / diff check                       = PASS
```

## Exit

```text
EOS outbox publisher       = CURRENT PLATFORM PROCESS
existing transaction reuse = PASS
demo runtime dependency    = NONE
wrong signed trust         = FAIL-CLOSED
restart / idempotent replay= PASS
protected PostgreSQL smoke = PASS
database migration         = NONE
NeX-EOS Slice Gate         = PASS
next slice                 = GB2-CA00-S08
```
