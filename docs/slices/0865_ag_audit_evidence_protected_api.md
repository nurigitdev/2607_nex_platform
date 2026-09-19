# Slice 0865: AG Audit Evidence Protected API

## Goal

Expose the Slice 0864 package builder and verifier through protected AG routes
without allowing callers to inject audit events or evidence-export records.

## Routes

- `POST /admin/v1/audit-integrity/evidence-packages`
- `POST /admin/v1/audit-integrity/evidence-packages/verify`

The create route accepts only a source trace ID, optional expected event IDs,
and optional required event types. Events and exports are selected from the
server-side `service_operational_events` and `ag_ev_exports` stores with a
bounded 500-row read. The response contains a redacted package and its
independent verification result.

The verify route accepts exactly one `package` field and returns only the safe
verification projection. It does not echo a caller-supplied package or any
unknown fields. A caller-supplied package ID is returned and audited only after
its manifest hash, package hash, and deterministic package ID all match.

Both routes reuse the established AG operator authorization boundary: valid
service principals with the service scope or user principals with the `admin`
role. Package generation and verification emit metadata-only operational events.
No table or migration is added.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_ag_audit_integrity.py \
  tests/test_nex_ag_audit_correlation.py \
  tests/test_nex_ag_audit_evidence_package.py \
  tests/test_nex_ag_audit_evidence_api.py \
  --cov=nex_ag.audit_integrity --cov=nex_ag.audit_correlation \
  --cov=nex_ag.audit_evidence_package --cov=nex_ag.audit_evidence_api \
  --cov-branch --cov-report=term-missing
```
