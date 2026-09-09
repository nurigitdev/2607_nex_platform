# Slice 0630: S63 Operator Review Evidence Closure

Slice 0630 closes S63 by checking the AG-owned operator review note and
redacted evidence export capability track.

## Scope

- Verifies required S63 files, migrations, contracts, smoke scripts, tests, and
  Slice 0621-0630 docs.
- Confirms the short AG-owned tables remain `ag_op_notes` and `ag_ev_exports`.
- Confirms note storage remains hash/preview only and export storage remains a
  redacted manifest plus SHA-256 hashes.
- Confirms the default quality gate includes boundary, note PostgreSQL smoke,
  export PostgreSQL smoke, and closure checkpoints.
- Confirms protected PostgreSQL smoke evidence exists for both note and export
  paths against `nex_ag_test`.

## Decision

- No new database table is added in Slice 0630.
- `nex-ag` owns operator review notes and redacted evidence export records.
- Source service records remain read-only from AG's perspective.
- Raw operator notes, raw evidence bodies, raw prompts, raw source text, storage
  paths, raw database URLs, and raw idempotency keys remain outside closure
  evidence.

## Verification

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_s63_operator_review_evidence_closure.py tests/test_s63_operator_review_evidence_closure.py
PYTHONPATH=scripts/smoke ./.venv/bin/pytest tests/test_s63_operator_review_evidence_closure.py -q --cov=run_s63_operator_review_evidence_closure --cov-branch --cov-report=term-missing
PYTHONPATH=scripts/smoke ./.venv/bin/python scripts/smoke/run_s63_operator_review_evidence_closure.py --summary
./scripts/quality/run_quality_gate.sh
```

## Expected Summary

```text
s63_operator_review_evidence_closure=pass slice_range=0621-0630 required_files=31 boundary=ag_owned_operator_review_notes_redacted_exports note_table=ag_op_notes export_table=ag_ev_exports smoke=test_db_note_and_export
```
