# Slice 0621: AG operator review note/export boundary audit

## Scope

Start S63 by freezing the AG-owned boundary for operator review notes and
redacted evidence exports before adding generic note/export tables or routes.

## Decision

- No database table is created in Slice 0621.
- AG may write its own operator review metadata, but it must not mutate source
  records owned by AE, CX, MO, or OA.
- The short candidate table names are `ag_op_notes` and `ag_ev_exports`.
- Source targets should be stored in indexable columns:
  `target_service`, `target_kind`, `target_id`, `trace_id`, and `request_id`.
- Free-text operator notes should be stored as hash + short preview only.
- Evidence export records should store a redacted evidence manifest plus hashes.
  Export body/file storage is deferred until the manifest contract is stable.
- Create routes must require OA admin claims and idempotency keys.
- PostgreSQL smoke must use the real `nex_ag_test` DB once note/export
  persistence is added.

## Guardrails

- Do not copy raw prompts, generation outputs, source document text, provider
  payloads, database URLs, service tokens, provider keys, local storage paths,
  source service record blobs, or artifact binary payloads into AG review
  records.
- AG read/projection surfaces may expose note/export counts and latest safe
  previews later, but source service records remain read-only through service
  APIs.
- AG-owned write models should follow the existing operator disposition pattern:
  store review metadata in AG and retain only redacted/hash evidence.

## Implementation

- Added
  `scripts/smoke/run_ag_operator_review_note_export_boundary_audit.py`.
- Added regression coverage for pass/fail evidence, source-token failures,
  table-name length checks, protected env redaction, helper behavior, and CLI
  output.
- Registered the audit in the default quality gate.
- Indexed Slice 0621 and added AG README notes.

## Evidence

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_ag_operator_review_note_export_boundary_audit.py tests/test_ag_operator_review_note_export_boundary_audit.py
PYTHONPATH=scripts/smoke ./.venv/bin/pytest tests/test_ag_operator_review_note_export_boundary_audit.py -q --cov=run_ag_operator_review_note_export_boundary_audit --cov-branch --cov-report=term-missing
PYTHONPATH=scripts/smoke ./.venv/bin/python scripts/smoke/run_ag_operator_review_note_export_boundary_audit.py --summary
./scripts/quality/run_quality_gate.sh
```

Observed audit summary:

```text
ag_operator_review_note_export_boundary_audit=pass paths=16/16 tokens=26/26 token_groups=7/7 tables=2/2 boundary=ag_owned_operator_review_notes_redacted_exports note_table=ag_op_notes export_table=ag_ev_exports next=Slice_0622
```

Observed targeted coverage:

```text
tests/test_ag_operator_review_note_export_boundary_audit.py: 6 passed
run_ag_operator_review_note_export_boundary_audit.py statement_coverage=100% branch_coverage=100%
```

Observed quality gate:

```text
4392 passed, 1 warning
statement_coverage=98.58% threshold=95.00%
branch_coverage=95.70% threshold=85.00%
contract_validation=pass schemas=70 examples=101 negative_examples=75 openapi=7
```

## Next

- Slice 0622 should add the `ag_op_notes` schema/store foundation using the
  boundary fixed here.
