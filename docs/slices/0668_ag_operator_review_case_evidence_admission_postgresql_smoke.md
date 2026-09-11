# Slice 0668: AG operator review case evidence/admission PostgreSQL smoke evidence

## Intent

Add protected PostgreSQL smoke evidence that the S67 case evidence-link and
action-admission runtime surfaces work with the real AG test database stores.

## Scope

- Add
  `scripts/smoke/run_ag_operator_review_case_evidence_admission_postgres_smoke.py`.
- Keep the write smoke opt-in with
  `NEX_AG_OPERATOR_REVIEW_CASE_EVIDENCE_ADMISSION_POSTGRES_SMOKE=1`.
- Run AG migrations against `NEX_AG_TEST_DATABASE_URL` before executing the
  write path.
- Create an operator-review case through the protected route, persist a matching
  operator note and redacted evidence export through PostgreSQL stores, then
  read:
  - `GET /admin/v1/operator-review/cases/{case_id}/workbench-detail`
  - `GET /admin/v1/operator-review/cases/{case_id}/evidence-links`
  - `GET /admin/v1/operator-review/cases/{case_id}/action-admission?action_type=RESOLVE`
- Verify direct PostgreSQL persistence for:
  - `ag_op_cases`
  - `ag_op_notes`
  - `ag_ev_exports`

## Evidence Boundary

- The smoke records only the redacted database URL.
- Raw operator notes, raw evidence bodies, and idempotency keys are rejected by
  the evidence redaction guard.
- Workbench detail keeps evidence/admission as summary plus links; the dedicated
  evidence-link and action-admission routes remain authoritative.
- Default quality-gate execution remains safe and skips the DB write path unless
  the opt-in environment flag is set.

## Local Test DB Smoke

Use the test database only:

```bash
NEX_AG_OPERATOR_REVIEW_CASE_EVIDENCE_ADMISSION_POSTGRES_SMOKE=1 \
NEX_AG_TEST_DATABASE_URL='postgresql+psycopg://nex_ag_user:***@127.0.0.1:5432/nex_ag_test' \
./.venv/bin/python scripts/smoke/run_ag_operator_review_case_evidence_admission_postgres_smoke.py --summary
```

Expected summary shape:

```text
ag_operator_review_case_evidence_admission_postgres_smoke=pass service=nex-ag db_env=NEX_AG_TEST_DATABASE_URL target_id=... cases=1 notes=1 exports=1 deleted_cases=1 deleted_notes=1 deleted_exports=1
```

## Verification

- Targeted smoke regression tests with branch coverage.
- Protected live PostgreSQL smoke against `nex_ag_test`.
- Full quality gate.
