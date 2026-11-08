# NeX Platform v2.1 E2E Step 4 Reliability Hardening v1.5

This hardening closes E2E-08 / E2E-09 / E2E-10 findings.

Canonical machine contracts are stored in owner product folders:

AE:
- runtime-job-v2.1.schema.json
- runtime-job-attempt-v2.1.schema.json
- retry-disposition-v2.1.schema.json
- reconciliation-case-v2.1.schema.json
- reconciliation-outcome-v2.1.schema.json
- reconcile-execution-job-payload-v2.1.schema.json
- 003_ae_runtime_job_v2_1.sql
- 004_ae_reconciliation_v2_1.sql
- reliability_protocols_v2_1.py

NSL:
- hardened nsl-result-summary-v2.1.schema.json
- idempotency-record-v2.1.schema.json
- retry-safety-evidence-v2.1.schema.json
- nsl-reconciliation-evidence-v2.1.schema.json
- 001_nsl_idempotency_v2_1.sql
- hardened nsl_integration_protocols_v2_1.py

Frozen invariants are unchanged.
