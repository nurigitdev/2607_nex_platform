# P9-S09: Fenced Stale-RUNNING Recovery

## Scope

P9-S09 closes the common JobQueue crash gap for `WA_EVIDENCE_INGEST`
without introducing an AE RuntimeJob, a second queue authority, or a new table.
It reuses:

```text
service_jobs
service_worker_heartbeats
SqlAlchemyJobQueue
shared WorkerRunner
```

The WA-specific composition adds `SqlAlchemyWaJobFenceStore` and
`WaFencedJobQueue`. The base queue remains the enqueue and claim authority;
the wrapper captures the persisted `(job_id, RUNNING, locked_by, locked_at)`
claim and requires that exact tuple for complete, fail, retry, or dead-letter
settlement.

## Recovery Policy

```text
NEX_WA_STALE_JOB_SECONDS default = 300
allowed range                    = 60..3600
```

A Job is recoverable only when all conditions hold:

```text
job_type = WA_EVIDENCE_INGEST
status = RUNNING
locked_at < observed_at - stale threshold
owner heartbeat is absent or older than the same cutoff
```

Recent claims and old claims with a current owner heartbeat are refused.
Recovery uses PostgreSQL `FOR UPDATE ... SKIP LOCKED` and an update CAS over
`job_id + status + locked_by + locked_at`.

## Recovery Outcomes

When another attempt remains, the stale Job returns to `QUEUED` and is
immediately eligible. When attempts are exhausted or retry is disabled, it is
terminally `FAILED` with a dead-lettered `WA_JOB_STALE_RECOVERED` error.

Any settlement from the prior claim fails with the typed code:

```text
WA_JOB_OWNERSHIP_LOST
```

The new owner can claim and settle the requeued Job normally. This preserves
the common JobQueue as the sole durable queue while making WA crash recovery
fenced and restart-safe.

## Actual PostgreSQL Evidence

The protected smoke used the actual local target:

```text
database = nex_wa_test
role     = nex_wa_user
```

It proved:

```text
recent RUNNING claim refusal              = PASS
live-heartbeat stale recovery refusal     = PASS
stale RUNNING requeue                     = PASS
attempt-exhausted dead-letter             = PASS
old complete/fail/retry rejection         = PASS
new owner completion                      = PASS
two concurrent recoverers / one CAS winner = PASS
post-smoke zero residue                   = PASS
```

The preceding P9-S08 PostgreSQL consumer smoke was rerun with the fenced
runtime composition and remained green.

## Quality Evidence

```text
focused unit regression       = 53 passed
actual PostgreSQL smokes      = 2 passed
P9-S09 Slice Gate             = 152 passed, 7 skipped
Slice statement/branch cover  = 97%
contract validation           = 211 schemas / 275 examples / 235 negatives / 9 OpenAPI
ruff                           = PASS
```

The seven skipped tests are protected PostgreSQL smokes from earlier WA
Slices. The P9-S08 and P9-S09 smokes were explicitly enabled and executed.

## Exit

```text
fenced stale recovery = PASS
duplicate recovery    = prevented
old owner settlement  = invalidated
schema migration      = none
next Slice            = P9-S10
```
