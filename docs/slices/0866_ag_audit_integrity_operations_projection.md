# Slice 0866: AG Audit Integrity Operations Projection

## Goal

Expose a redacted operational read model for S87 package activity and evidence
export hash readiness, and include it in the unified AG dashboard.

## Projection

`build_audit_evidence_operations_projection(...)` reads only existing
`service_operational_events` and `ag_ev_exports` records. It reports:

- package generation and verification action counts;
- failed verification action counts;
- total, hash-ready, and invalid-hash export counts;
- bounded recent package actions and export metadata;
- per-source READY, NOT_CONFIGURED, FILTERED, or UNAVAILABLE state;
- explicit READY, ATTENTION, EMPTY, FILTERED, or SOURCE_UNAVAILABLE integrity
  state.

The projection is available at `GET /admin/v1/operations/audit-integrity` and as
the `audit_integrity` section of the unified operations dashboard. It excludes
event messages/details, evidence manifests, operator references, credentials,
and storage paths. Existing test environments without an export store report
`NOT_CONFIGURED` rather than degrading unrelated dashboard sections.

No table or migration is added.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_ag_audit_evidence_operations.py \
  tests/test_nex_ag_audit_evidence_api.py \
  --cov=nex_ag.audit_evidence_operations \
  --cov=nex_ag.audit_evidence_api --cov-branch --cov-report=term-missing
```
