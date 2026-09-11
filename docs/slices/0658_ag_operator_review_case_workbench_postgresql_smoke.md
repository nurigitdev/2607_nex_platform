# Slice 0658: AG operator review case workbench PostgreSQL smoke evidence

## Intent

Add protected PostgreSQL smoke evidence for the S66 case workbench queue,
detail, and timeline surfaces before moving to privacy regression and closure.

## Scope

- Add `scripts/smoke/run_ag_operator_review_case_workbench_postgres_smoke.py`.
- Keep the smoke opt-in with
  `NEX_AG_OPERATOR_REVIEW_CASE_WORKBENCH_POSTGRES_SMOKE=1`.
- Run AG migrations against `NEX_AG_TEST_DATABASE_URL` before write smoke
  execution.
- Create a case, apply an assignment action, and read:
  - `GET /admin/v1/operator-review/cases/queue`
  - `GET /admin/v1/operator-review/cases/{case_id}/workbench-detail`
  - `GET /admin/v1/operator-review/cases/{case_id}/timeline`
- Verify direct PostgreSQL persistence for both:
  - `ag_op_cases`
  - `service_operational_events`

## Evidence Boundary

- The smoke records only the redacted database URL.
- Raw action comments and raw idempotency keys are rejected by the evidence
  redaction guard.
- Timeline evidence is operational-events-first. No S66 case action history
  table is introduced.
- Default quality-gate execution remains safe and skips the DB write path unless
  the opt-in environment flag is set.

## Local Test DB Smoke

Use the test database only:

```bash
NEX_AG_OPERATOR_REVIEW_CASE_WORKBENCH_POSTGRES_SMOKE=1 \
NEX_AG_TEST_DATABASE_URL='postgresql+psycopg://nex_ag_user:nuri1004@127.0.0.1:5432/nex_ag_test' \
./.venv/bin/python scripts/smoke/run_ag_operator_review_case_workbench_postgres_smoke.py --summary
```

Expected summary shape:

```text
ag_operator_review_case_workbench_postgres_smoke=pass service=nex-ag db_env=NEX_AG_TEST_DATABASE_URL target_id=... cases=1 events=2 deleted_cases=1 deleted_events=2
```

## Verification

- Targeted smoke regression tests.
- Protected live PostgreSQL smoke against `nex_ag_test`.
- Full quality gate.
