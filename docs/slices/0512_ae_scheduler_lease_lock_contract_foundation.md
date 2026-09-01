# Slice 0512: AE Scheduler Lease Lock Contract Foundation

## Scope

Define the AE artifact retention scheduler lease/lock contract before adding
persistent lease state or any continuous daemon loop.

## Contract

- Lease requests use `ae_artifact_retention_scheduler_lease_request.v1`.
- Lease records use `ae_artifact_retention_scheduler_lease_record.v1`.
- Lease decisions use `ae_artifact_retention_scheduler_lease_decision.v1`.
- The first supported operation is `manual_tick_once`.
- The default lease owner is `ae-artifact-retention-scheduler-manual-once`.
- The lease TTL inherits the scheduler tick lock TTL: `600` seconds.
- The stale window remains `3600` seconds.

The contract keeps S52 conservative:

```text
lease request -> lease record -> acquire/busy decision -> explicit release
```

## Guardrails

- Scheduler daemon auto-start remains disabled.
- Continuous loop execution remains disallowed before the lease repository.
- Physical delete automation remains disabled.
- Lease evidence is metadata-only and must not include database URLs, local
  storage paths, raw artifact payloads, or raw execution payloads.
- No job enqueue or worker execution is performed by the contract itself.

## Evidence

Regression coverage is focused on:

- request, record, decision, release, and summary happy paths;
- TTL, timestamp, schema, status, guardrail, and metadata validation edges;
- busy decisions when another held lease blocks acquisition;
- redaction safety through the existing artifact retention payload guard.

## Next

- Slice 0513: Scheduler lease repository adapter.
- Slice 0514: Scheduler tick once runner.
- Slice 0515: Scheduler tick once PostgreSQL smoke evidence.
