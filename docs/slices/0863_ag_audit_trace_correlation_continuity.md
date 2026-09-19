# Slice 0863: AG Audit Trace Correlation Continuity

## Goal

Detect breaks between verified AG operational events, request/trace correlation,
and evidence-export references without exposing event or evidence bodies.

## Contract

`build_audit_correlation_continuity_report(...)`:

- reuses the Slice 0862 event-integrity report and projects only valid events;
- groups event IDs, event types, request IDs, subject references, and evidence
  export IDs by trace ID;
- rejects a request ID that spans more than one trace;
- reports valid events without a trace ID;
- detects missing expected traces and required event types;
- validates evidence-export IDs and SHA-256 hashes;
- detects duplicate exports and exports whose trace is absent;
- bounds each verification to 500 exports;
- emits a deterministic canonical report hash independent of input order and
  `checked_at`;
- reports `CONTIGUOUS`, `FAILED`, or `NO_CORRELATION` explicitly.

The report is read-only and adds no database table or migration. Event messages,
event details, evidence bodies, storage paths, and credentials are never copied
into the result.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_ag_audit_integrity.py \
  tests/test_nex_ag_audit_correlation.py \
  --cov=nex_ag.audit_integrity --cov=nex_ag.audit_correlation \
  --cov-branch --cov-report=term-missing
```
