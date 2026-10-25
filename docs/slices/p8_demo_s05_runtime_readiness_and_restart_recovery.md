# P8-DEMO-S05: Runtime Readiness and Restart Recovery

## Outcome

The three background commands admitted by P8-DEMO-S04 now have a shared,
database-backed lifecycle. Each command validates its service database and
required tables, uses the worker connection-pool profile, publishes durable
heartbeats, runs recovery before polling, handles `SIGINT` and `SIGTERM`, and
closes its engine on exit.

The installed processes are:

- `nex-ae-agent-runtime-worker` in `nex_ae_dev`;
- `nex-wc-event-delivery-worker` in `nex_wc_dev`;
- `nex-eos-outbox-publisher` in `nex_eos_dev`.

EOS migration `2515_eos_worker_heartbeat` gives the EOS-owned process the same
durable liveness contract already used by AE and WC. Its identifiers remain
short enough for PostgreSQL.

## Execution Boundary

This Slice activates the installed process lifecycle, readiness checks,
recovery inspection, graceful shutdown, and restart evidence. It does not yet
claim or mutate business work. Every process therefore reports:

```text
execution_enabled = true
domain_claiming_enabled = false
domain_claiming_activation = P8-DEMO-S10
```

This boundary prevents an installed but incomplete delivery composition from
silently consuming durable work. P8-DEMO-S10 owns activation of the complete
AE execution, WC delivery, and EOS publication journey.

## Actual PostgreSQL Evidence

Adding EOS migration `2515` changed the source migration inventory, so the old
S02 backup binding was correctly rejected. A new protected seven-database
backup was created before migration:

```text
backup_id = 20261025T110321Z-8ddfd8800c1c6fb6
services = 7
migration_state = CURRENT
newly_applied = nex-eos/2515_eos_worker_heartbeat
```

All three commands then passed a protected `--check` and two consecutive
one-cycle executions against the actual dev databases. Recovery observed no
claimable work, and each second start safely reused its durable heartbeat row.

Final heartbeat evidence:

```text
nex-ae-api  ae-demo-agent-runtime-1     STOPPED  time_order=true
nex-wc      wc-demo-event-delivery-1    STOPPED  time_order=true
nex-eos     eos-demo-outbox-publisher-1 STOPPED  time_order=true
```

All rows contain the admitted process ID and `demo_release=true`; command
output and reports contain neither database URLs nor secrets. The `VO00`
fixture remains intentionally preserved.

## Verification

- focused lifecycle, process manifest, and service command unit tests;
- failure paths for configuration, table admission, recovery, cycle status,
  heartbeat error publication, shutdown tokens, and signal restoration;
- existing worker heartbeat and S131 vertical-spine regression;
- protected migration and runtime smoke against actual AE/WC/EOS dev DBs;
- Slice Gate with statement and branch coverage targets.

P8-DEMO-S05 closes runtime readiness and restart recovery. P8-DEMO-S06 may now
package the expanded installed process set into a complete OCI release set.
