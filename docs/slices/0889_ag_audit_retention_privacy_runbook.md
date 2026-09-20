# Slice 0889: AG audit retention privacy and failure runbook

## Goal

Turn S89 retention and purge failure boundaries into deterministic,
privacy-safe operator evidence and actions.

## Implementation

- Exercises default mock mode, execute-disabled posture, non-recoverable
  external archive rejection, missing receipt, active grace period, source hash
  mismatch, missing source, missing confirmation, concurrent change, successful
  purge, and idempotent retry.
- Requires mock receipts to remain purge-ineligible and requires an explicitly
  enabled external provider plus a recoverable sealed receipt before execution.
- Normalizes concurrency and archive errors without exposing source payloads,
  archive object references, database URLs, credentials, or confirmation input.
- Defines operator actions for all exercised failures plus PostgreSQL
  connectivity, missing migration/indexes, and smoke cleanup failure.
- Requires every Slice 0881-0888 document, the quality-gate hook, and the Slice
  0888 live evidence for two purges, two indexes, and zero DB residue.
- Introduces no table or migration.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_ag_audit_retention_privacy_runbook_evidence.py \
  --cov=run_ag_audit_retention_privacy_runbook_evidence \
  --cov-branch --cov-report=term-missing

./.venv/bin/python \
  scripts/smoke/run_ag_audit_retention_privacy_runbook_evidence.py \
  --summary
```

Observed verification:

```text
focused runbook tests: 8 passed
runbook evidence statement/branch: 100%
ag_audit_retention_privacy_runbook=pass surfaces=14 privacy=True postgres=True runbook=True
aggregate regression: 6149 passed, 1 known warning
statement=74703/75584=98.834409398815%
branch=17482/18132=96.415177586587%
```
