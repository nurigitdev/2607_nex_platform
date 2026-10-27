# NeX-WA Database

NeX-WA owns `nex_wa_dev` and `nex_wa_test` through `nex_wa_user`.
P9-S02 freezes the owner-local migration stream as follows:

```text
2600_wa_schema_migrations_baseline
2601_wa_service_job_queue
2602_wa_worker_heartbeat
2603_wa_work_evidence          (P9-S03)
2604_wa_work_asset             (P9-S04)
2605_wa_work_asset_evidence    (P9-S04)
```

The first three migrations reuse the current Platform common runtime table
contracts. The WA JobQueue foundation includes the later-admitted
`replay_lineage` field directly instead of replaying the historical two-step
`0083`/`0135` evolution used by older services.
No cross-database foreign key is permitted.
