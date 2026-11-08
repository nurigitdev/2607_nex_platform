# P9-S08: WA Evidence Consumer and Source Adapter Port

## Scope

P9-S08 activates `nex-wa-evidence-consumer` without introducing source-specific
AE/WC behavior. It composes the existing platform runtime components:

```text
SqlAlchemyJobQueue
WorkerRunnerConfig / run_worker_once / run_worker_batch
WorkerHeartbeatEmitter
ServiceLogEmitter
```

Worker identity is fixed as:

```text
service_id  = nex-wa
process_id  = nex-wa-evidence-consumer
worker_type = wa.evidence_consumer
job_type    = WA_EVIDENCE_INGEST
```

## Adapter Boundary

`WaEvidenceSourceAdapter` and `WaEvidenceSourceAdapterRegistry` provide the
fail-closed extension point for later source-owner integration. The registry is
ready only when both initial external types are installed:

```text
AE_AGENT_RESULT
AE_ARTIFACT
```

P9-S08 uses only `ControlledWaEvidenceSourceAdapter`. It performs no AE/WC HTTP
call and is explicitly a deterministic lifecycle-test adapter.

The machine-readable `wa_source_normalized_envelope.v1` contract contains only
source identity, source hash, owner, occurrence time, and inspection status.
Unknown/raw fields are rejected.

## Runtime Behavior

For each claimed Job the consumer:

```text
revalidates the reference-only intake payload
resolves the adapter by admitted source_type
normalizes the source envelope
matches tenant/source identity/revision/hash
returns a bounded verification summary
lets the shared WorkerRunner complete or retry the Job
```

Unknown adapters, malformed Job payloads, raw fields, and mismatched envelopes
never complete successfully. Shared retry semantics keep retryable failures in
`QUEUED`; no WorkEvidence or WorkAsset mutation occurs in this Slice.

## Startup and Shutdown

Startup readiness verifies:

```text
all WA migrations current
service_jobs reachable
service_worker_heartbeats reachable
wa_work_evidence reachable
wa_work_asset reachable
wa_work_asset_evidence reachable
adapter registry complete
```

Graceful stop emits `STOPPING` followed by `STOPPED` heartbeat state.

## Actual PostgreSQL Evidence

Actual `nex_wa_test / nex_wa_user` verification proved:

```text
migration and table readiness = PASS
durable claim via JobQueue     = PASS
controlled source inspection  = PASS
Job completion                = SUCCEEDED
attempt_count                 = 1
heartbeat terminal state      = STOPPED
post-smoke zero residue       = PASS
```

## Quality Evidence

```text
focused consumer regression = 24 passed
actual PostgreSQL smoke     = 1 passed
P9-S08 Slice Gate           = 148 passed, 5 skipped
Slice statement coverage    = 99.71%
Slice branch coverage       = 98.47%
consumer/adapter coverage   = 100.00%
contract validation         = 211 schemas / 275 examples / 235 negatives / 9 OpenAPI
```

The five skipped tests are earlier protected PostgreSQL smokes. The P9-S08
PostgreSQL smoke was explicitly enabled and executed.

## Exit

```text
consumer lifecycle       = PASS
source adapter port      = PASS
claim / complete / retry = PASS
graceful stop            = PASS
heartbeat and log bridge = PASS
next Slice               = P9-S09
```
