# Slice 0864: AG Audit Evidence Package Builder

## Goal

Build and independently verify a deterministic, redacted evidence package from
the Slice 0862 integrity report, Slice 0863 correlation report, and existing
`ag_ev_exports` records.

## Contract

`build_audit_evidence_package(...)`:

- requires the correlation report to reference the supplied integrity hash;
- requires each export to be linked by the correlation report;
- projects only export ID, trace ID, evidence hash, item count, status, and
  redaction profile;
- excludes stored manifests, operator references, event bodies, credentials,
  endpoint values, and storage paths;
- sorts export references and uses canonical JSON SHA-256 hashes;
- emits deterministic manifest, package hash, and package ID values independent
  of generation time and input order;
- reports `VERIFIED`, `FAILED`, or `NO_EVIDENCE` without rewriting source data.

`verify_audit_evidence_package(...)` recomputes both hashes and checks schema,
counts, duplicate IDs, export hash shape, package identity, and redaction flags.
This makes copied packages self-verifying and exposes tampering as explicit issue
codes. The Slice adds no table or migration.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_ag_audit_integrity.py \
  tests/test_nex_ag_audit_correlation.py \
  tests/test_nex_ag_audit_evidence_package.py \
  --cov=nex_ag.audit_integrity --cov=nex_ag.audit_correlation \
  --cov=nex_ag.audit_evidence_package --cov-branch --cov-report=term-missing
```
