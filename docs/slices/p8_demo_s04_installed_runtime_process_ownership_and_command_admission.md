# P8-DEMO-S04: Installed Runtime Process Ownership and Command Admission

## Outcome

The Demo release now has an additive, source-backed process inventory. It does
not mutate the frozen S131/S143 six-image runtime evidence.

The installed set contains seven backend APIs, AE Web, and three background
processes:

- `nex-ae-agent-runtime-worker`
- `nex-wc-event-delivery-worker`
- `nex-eos-outbox-publisher`

The AE dispatcher is not a second queue or daemon. It is the DB-lease and
capability-aware assignment component embedded in the AE executable worker.
That ownership is explicit in the manifest.

## Source-backed decisions

| Concern | Decision |
| --- | --- |
| AE dispatcher | embedded in the AE runtime worker through `SqlAlchemyAgentRuntimeAssignmentSource` |
| AE executable worker | installed process owned by `nex-ae-runtime` |
| WC handoff and result delivery | adapters hosted by one WC event-delivery worker using the WC JobQueue |
| WC approval event publication | same WC worker ownership; executable composition follows in S05 |
| EOS outbox publication | installed process owned by `nex-eos-runtime` |
| database pools | APIs use `api`; background processes use `worker` |
| liveness | API HTTP probes; background PostgreSQL heartbeat contracts |
| shutdown/restart | graceful active-unit completion plus durable lease/outbox replay |

An in-test function call is explicitly not admitted as a release process.

## Command admission

The service-owned module commands are now present and support `--check`:

```text
python -m nex_ae_api.demo_runtime worker --check
python -m nex_wc.demo_runtime events --check
python -m nex_eos.demo_runtime outbox --check
```

S04 admits the packaged command and exact ownership only. Running a command
without `--check` fails closed until P8-DEMO-S05 composes its database-backed
loop, heartbeat, signal handling, and restart recovery.

## Verification

- Demo process inventory and eight-artifact ownership validation
- source module admission for every process/component
- worker pool, heartbeat, SIGTERM, and restart-contract validation
- all three service commands pass `--check`
- execution before S05 fails closed

P8-DEMO-S04 is complete when the focused Slice Gate passes. S05 may then turn
the admitted commands into executable, restart-safe processes.
