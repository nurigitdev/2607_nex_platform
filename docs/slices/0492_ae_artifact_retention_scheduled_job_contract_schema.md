# Slice 0492: AE artifact retention scheduled job contract/schema

Add the first S50 scheduled retention JobQueue envelope so AE can queue dry-run
retention work without enabling scheduler daemon startup or physical delete
automation.

## Scope

- Added `ae_artifact_retention_scheduled_job.v1` under generation contracts.
- Added positive and negative contract fixtures for queued dry-run scheduled
  retention jobs.
- Added runtime builders and validators for scheduled job payloads and
  `common_job.v1` envelopes.
- Added regression coverage for READY/NOOP handling, common job fields,
  idempotency, links, redaction flags, and payload/job validation edges.

## Decisions

- The scheduled job type is `ae.artifact_retention.scheduled_execution`.
- Only READY scheduled execution commands can become queued jobs.
- Job payloads embed the scheduled command metadata and command summary, but no
  raw prompt, rendered payload, source content, storage locator, DB URL, or
  provider secret.
- Jobs are retryable with `max_attempts=3`.
- Physical delete automation remains disabled; the job contract only prepares
  dry-run scheduled execution admission.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ae_artifacts.py -q --cov=nex_ae_api.artifacts --cov-branch --cov-report=term-missing
./.venv/bin/python scripts/quality/validate_contracts.py
```
