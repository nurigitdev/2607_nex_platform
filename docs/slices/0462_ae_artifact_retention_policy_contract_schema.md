# Slice 0462: AE artifact retention policy contract/schema

Freeze the metadata-only retention policy contract before retention candidate
queries are added.

## Scope

- Added `ae_artifact_retention_policy.v1` JSON Schema.
- Added a positive 30-day logical purge policy example and a negative
  `storage_ref` leak fixture.
- Added AE artifact policy helpers in `nex_ae_api.artifacts`.
- Added regression coverage for defaults, 15-day override, invalid retention
  days, policy validation failures, and redaction guards.

## Decisions

- `artifact_status=DELETED` remains the logical purge flag for this track.
- Physical purge is disabled in the policy contract through Slice 0465.
- Candidate scans must be dry-run and metadata-only.
- The default retention window is 30 days after logical purge. 15 and 30 days
  are the first explicitly supported operator presets.
- The planned scheduled batch window is 02:00-05:00 in `Asia/Seoul`.

## Evidence

```text
./.venv/bin/pytest tests/test_nex_ae_artifacts.py -q --cov=nex_ae_api.artifacts --cov-branch --cov-report=term-missing
./.venv/bin/python scripts/quality/validate_contracts.py
```
