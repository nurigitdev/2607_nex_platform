# Slice 0635: AG Operator Review Issue Candidate Correlation

Slice 0635 connects operator review workbench attention to the AG operations
issue-candidate surface.

## Scope

- Adds `operator_review_attention_required.v1` to the operations issue-candidate
  rule registry.
- Extends issue-candidate projection building so `operator_review_workbench`
  attention items produce a safe AG-owned candidate.
- Wires `/admin/v1/operations/issue-candidates` to the same operator-review
  note/export stores used by the dashboard and workbench routes.
- Updates the mock operations dashboard smoke so the issue-candidate count
  includes operator-review attention.

## Boundary

- No new table is added.
- The candidate is read-only and does not mutate note/export state.
- Failed evidence exports produce an `ERROR` candidate; active high-urgency or
  open notes produce `WARNING` candidates.
- Candidate signals include only safe target refs, counts, runbook ids, and
  operator action names.

## Verification

```bash
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operations.py -q --cov=nex_ag.operations --cov-branch --cov-report=term-missing
PYTHONPATH=scripts/smoke ./.venv/bin/pytest tests/test_smoke_helpers.py -q
./scripts/quality/run_quality_gate.sh
```
