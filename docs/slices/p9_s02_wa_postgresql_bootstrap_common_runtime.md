# P9-S02: WA PostgreSQL Bootstrap and Common Runtime Persistence

## Scope

P9-S02 activates the owner-local NeX-WA PostgreSQL foundation. It introduces
only the Platform migration ledger, shared JobQueue, and worker heartbeat
tables. WorkEvidence and WorkAsset domain tables remain owned by P9-S03 and
P9-S04.

```text
database = nex_wa_dev / nex_wa_test
role     = nex_wa_user
runtime  = NEX_WA_DATABASE_URL
test     = NEX_WA_TEST_DATABASE_URL
```

## Migration Stream

```text
2600_wa_schema_migrations_baseline
2601_wa_service_job_queue
2602_wa_worker_heartbeat
```

The new WA JobQueue migration represents the current shared schema rather than
replaying historical service evolution. In particular, it includes
`replay_lineage`, which older services received through migration `0135`.
Actual PostgreSQL smoke initially detected this omission before the Slice was
committed; the foundation and test database were aligned and revalidated.

## Runtime Boundary

`WaPersistenceRuntime` reuses:

```text
nex_runtime.SqlAlchemyJobQueue
nex_runtime.SqlAlchemyWorkerHeartbeatStore
nex_runtime.SqlAlchemyUnitOfWork
nex_runtime database pool/session builders
```

API and evidence-consumer workloads receive separate configurable pools. The
runtime does not activate service-log or operational-event stores because P9-S02
does not create those tables. Public projections redact credentials, and WA
readiness fails closed when any required foundation migration is absent.

## Protected PostgreSQL Evidence

Actual target identity:

```text
database = nex_wa_test
role     = nex_wa_user
```

Verified behavior:

```text
fresh migration application                  = PASS
repeat migration, all versions skipped       = PASS
migration head current                        = PASS
wrong database/role URL rejected pre-connect = PASS
shared JobQueue enqueue/select                = PASS
worker heartbeat upsert/select                = PASS
wa_work_* tables absent                       = PASS
service_jobs residue after smoke              = 0
service_worker_heartbeats residue after smoke = 0
```

## Quality Evidence

```text
focused WA unit regression       = 24 passed
shared migration/runtime tests   = 61 passed
actual PostgreSQL protected smoke = 1 passed
Slice Gate statement coverage    = 100.00% (floor 96.00%)
Slice Gate branch coverage       = 100.00% (floor 94.00%)
contract validation              = PASS
```

## Exit

```text
WA database bootstrap       = PASS
common queue parity         = PASS
heartbeat persistence       = PASS
protected identity boundary = PASS
domain tables introduced    = NO
next Slice                  = P9-S03
```
