# Slice 0862: AG Audit Event Integrity Contract

## Goal

Add a deterministic, read-only contract that detects malformed, duplicate,
missing, or hash-mismatched operational events without exposing their message or
details.

## Contract

`build_audit_event_integrity_report(...)`:

- reuses the shared `operational_event.v1` validator;
- accepts at most 500 events per bounded verification;
- verifies timezone-aware ISO-8601 timestamps;
- deduplicates and checks explicit expected event IDs;
- compares optional expected SHA-256 event hashes;
- orders verified items by actual `(created_at, event_id)` time;
- hashes complete canonical events while returning metadata-only items;
- returns stable report hashes independent of `checked_at` and input order;
- never modifies source events;
- reports `VERIFIED`, `FAILED`, or `NO_EVENTS` explicitly.

The public report excludes event messages, details, raw payloads, credentials,
and storage paths. Event IDs, types, service IDs, severity, timestamps, safe
presence flags, and SHA-256 hashes remain available for operator verification.

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_ag_audit_integrity.py \
  --cov=nex_ag.audit_integrity --cov-branch --cov-report=term-missing
```
