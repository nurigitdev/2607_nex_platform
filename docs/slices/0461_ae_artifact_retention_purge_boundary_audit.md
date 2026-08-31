# Slice 0461: AE artifact retention/purge boundary audit

Start S47 by freezing the artifact retention and purge boundary before any
candidate read-model or batch deletion work is added.

## Scope

- Added `scripts/smoke/run_ae_artifact_retention_purge_boundary_audit.py`.
- Added regression coverage for the audit evidence, redaction rules, CLI output,
  and quality-gate/docs wiring.
- Confirmed `artifact_status=DELETED` is the first logical purge flag.
- Confirmed physical deletion and storage mutation remain deferred through
  Slice 0465.

## Decisions

- Logical purge is first-class and reversible through the existing lifecycle
  path: `MARK_DELETED` sets `artifact_status` to `DELETED`.
- Candidate retention defaults to 30 days after logical purge, with 15 and 30
  day presets explicitly documented for early operations review.
- Physical file deletion should be considered a later scheduled batch concern,
  targeted at a local 02:00-05:00 window, and must be guarded by a dry-run
  candidate query first.
- Slices 0461-0465 do not remove files, delete database rows, or mutate storage.

## Evidence

```text
./.venv/bin/pytest tests/test_ae_artifact_retention_purge_boundary_audit.py -q --cov=run_ae_artifact_retention_purge_boundary_audit --cov-branch --cov-report=term-missing
```

The audit summary is available through:

```text
./.venv/bin/python scripts/smoke/run_ae_artifact_retention_purge_boundary_audit.py --summary
```
