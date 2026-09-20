# Slice 0882: AG audit retention and archive policy

## Goal

Freeze one validated S89 policy before candidate selection, receipt persistence,
or guarded physical purge is implemented.

## Implementation

- Added `nex_ag.audit_retention` as the canonical S89 policy module.
- Kept `service_operational_events` and `ag_ev_exports` as source tables.
- Applied a 365-day default retention period to each source, configurable from
  30 through 3,650 days.
- Applied a 30-day archive grace period, configurable from 1 through 365 days
  and never longer than the shortest source retention period.
- Bounded each batch to 100 records by default and 500 records at maximum.
- Kept dry-run and explicit confirmation mandatory.
- Kept physical purge disabled by default. Enabling it requires `external`
  archive mode; development `mock` receipts can never open execute mode.
- Kept endpoint URLs, credentials, and archive object keys out of the policy.

## Configuration

| Variable | Default |
| --- | ---: |
| `NEX_AG_AUDIT_EVENT_RETENTION_DAYS` | `365` |
| `NEX_AG_EVIDENCE_EXPORT_RETENTION_DAYS` | `365` |
| `NEX_AG_ARCHIVE_GRACE_DAYS` | `30` |
| `NEX_AG_RETENTION_BATCH_SIZE` | `100` |
| `NEX_AG_ARCHIVE_PROVIDER_MODE` | `mock` |
| `NEX_AG_RETENTION_EXECUTE_ENABLED` | `false` |

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_ag_audit_retention.py \
  --cov=nex_ag.audit_retention --cov-branch --cov-report=term-missing
```

Observed verification:

```text
policy tests: 21 passed
policy module statement/branch: 100%
aggregate regression: 6038 passed, 1 known warning
statement=73786/74667=98.820094553149%
branch=17250/17900=96.368715083799%
```
