# Slice 0861: AG Audit Integrity and Evidence Boundary Audit

## Goal

Start S87 by fixing the ownership and storage boundary for audit-integrity
verification and safe evidence packages before adding new runtime behavior.

## Decision

- NeX-AG owns audit-integrity verification and evidence-package projection.
- Reuse `service_operational_events` as the audit-event source of record.
- Reuse `ag_ev_exports` as the redacted evidence-export source of record.
- Add no table or migration for S87. Existing JSON manifest fields can carry
  verification metadata without changing relational storage.
- Verification is read-only and deterministic. It must never rewrite historical
  audit events to make a failed report pass.
- Canonical manifests use sorted canonical JSON and SHA-256.
- Event ordering uses `(created_at, event_id)` so repeated verification produces
  the same result.
- Evidence packages may contain safe references, hashes, counts, timestamps,
  event types, service IDs, and trace/correlation IDs. Raw prompts, source text,
  provider payloads, credentials, endpoint URLs, and storage paths remain out.
- External notarization/signature services and cross-database transactions are
  not required for S87.
- Retention, archive, and physical purge remain assigned to S89.

Both table identifiers remain below the 30-character project limit:

- `service_operational_events`: 26 characters
- `ag_ev_exports`: 13 characters

## Slice Plan

- Slice 0861: boundary audit and refactoring checkpoint.
- Slice 0862: audit-event integrity verification contract.
- Slice 0863: trace/correlation continuity validation.
- Slice 0864: deterministic redacted evidence manifest/package builder.
- Slice 0865: protected evidence export API and authorization guardrails.
- Slice 0866: operations integrity projection and dashboard integration.
- Slice 0867: OpenAPI and JSON Schema contract hardening.
- Slice 0868: actual `nex_ag_test` PostgreSQL integrity smoke.
- Slice 0869: privacy, tamper/failure modes, and operator runbook.
- Slice 0870: S87 closure checkpoint.

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_ag_audit_integrity_evidence_boundary_audit.py --summary
```

Expected summary:

```text
ag_audit_integrity_evidence_boundary=pass tables=2 new_table=False mode=read_only_deterministic
```

```bash
./.venv/bin/pytest -q \
  tests/test_ag_audit_integrity_evidence_boundary_audit.py \
  --cov=run_ag_audit_integrity_evidence_boundary_audit \
  --cov-branch --cov-report=term-missing
```
