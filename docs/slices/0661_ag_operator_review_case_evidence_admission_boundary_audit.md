# Slice 0661: AG operator review case evidence/admission boundary audit

## Intent

Start S67 by freezing the AG-owned operator review case evidence-link and
action-admission boundary before adding new read models or routes.

## Scope

- Add `scripts/smoke/run_ag_operator_review_case_evidence_admission_boundary_audit.py`.
- Confirm S67 starts after the closed S66 case workbench loop.
- Confirm Slice 0661 adds no database table.
- Confirm evidence links reuse existing AG-owned sources:
  - `ag_op_cases`
  - `ag_op_notes`
  - `ag_ev_exports`
  - `service_operational_events`
- Confirm action-admission is preflight-only and does not replace the existing
  case action mutation route.
- Keep evidence linkage safe-ref/hash/preview first, with raw notes, evidence
  bodies, action comments, prompts, source text, storage paths, provider
  payloads, database URLs, service tokens, and idempotency keys excluded.

## Decision

- `nex-ag` owns the evidence/admission projection.
- The first implementation step after this audit is a case evidence-link read
  model.
- Evidence links should reuse `ag_op_notes` and `ag_ev_exports`; no dedicated
  evidence-link table is introduced in Slice 0661.
- Action-admission should derive from the same case action state machine used by
  mutations, and the mutation route remains the final authority.
- PostgreSQL smoke evidence for evidence/admission must use the real
  `nex_ag_test` database before S67 closure.
- The final pre-closure regression should prove evidence-link and
  action-admission surfaces do not leak raw note text, raw evidence bodies, raw
  action comments, prompts, source text, storage paths, provider credentials,
  database URLs, or idempotency keys.

## Verification

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_ag_operator_review_case_evidence_admission_boundary_audit.py tests/test_ag_operator_review_case_evidence_admission_boundary_audit.py
PYTHONPATH=scripts/smoke ./.venv/bin/pytest tests/test_ag_operator_review_case_evidence_admission_boundary_audit.py -q --cov=run_ag_operator_review_case_evidence_admission_boundary_audit --cov-branch --cov-report=term-missing
PYTHONPATH=scripts/smoke ./.venv/bin/python scripts/smoke/run_ag_operator_review_case_evidence_admission_boundary_audit.py --summary
./scripts/quality/run_quality_gate.sh
```

## Expected Summary

```text
ag_operator_review_case_evidence_admission_boundary_audit=pass paths=22/22 tokens=35/35 token_groups=7/7 tables=4/4 boundary=ag_owned_operator_review_case_evidence_admission evidence=ag_op_notes,ag_ev_exports admission=preflight next=Slice_0662
```
