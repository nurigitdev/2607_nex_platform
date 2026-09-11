# Slice 0660: S66 operator review case workbench closure

## Intent

Close S66 after the AG operator review case workbench queue, detail, timeline,
dashboard signal, PostgreSQL smoke, and privacy regression slices.

## Scope

- Add `scripts/smoke/run_s66_operator_review_case_workbench_closure.py`.
- Verify Slice 0651-0660 documentation is contiguous and indexed.
- Verify required runtime, migration, contract, OpenAPI, smoke, and regression
  files exist.
- Verify S66 remains AG-owned and read-model-first:
  - queue source: `ag_op_cases`
  - timeline source: `service_operational_events`
  - action history policy: `operational_events_first`
- Verify the protected `nex_ag_test` smoke and privacy regression runners are
  included in the default quality gate.

## Evidence Boundary

- The closure scans S66 docs and AG README for raw database URLs, shared local
  passwords, provider keys, raw action comments, raw resolution comments, raw
  prompts, raw source text, raw idempotency keys, and local storage paths.
- PostgreSQL smoke documentation keeps only the opt-in flag, environment
  variable name, and test database name. The password is masked.
- S66 does not create a separate queue, timeline, or action-history table.

## Verification

```text
s66_operator_review_case_workbench_closure=pass slice_range=0651-0660 required_files=37 boundary=ag_owned_operator_review_case_workbench_projection source_tables=ag_op_cases,service_operational_events smoke=test_db_case_workbench privacy=route_surface_regression
```

- Targeted closure regression tests.
- Full quality gate.
