# Slice 0897: AG to CX transition handoff package

## Goal

Produce a deterministic, redacted, tamper-evident package that defines what
NeX-CX inherits after NeX-AG service MVP acceptance.

## Handoff

- A package can be sealed only from an `ACCEPTED` NeX-AG report whose transition
  status is `READY_FOR_CX` and whose acceptance ID is canonical SHA-256.
- Eleven existing CX JSON Schema contracts and four implementation checkpoints
  are represented by repository-relative path and SHA-256 only.
- The manifest fixes OA identity, AE upload/chat, and MO provider execution as
  dependencies without copying their data into CX.
- Ownership boundaries preserve external source-byte storage, tenant/user
  owner scope, CX processing lineage, and AG's read-only redacted consumption.
- Object storage selection, vector-store separation, provider recertification,
  and CX capacity/DR certification remain explicit risks.
- The recommended next entry is an S91 CX current-state re-audit and refactoring
  checkpoint, not an assumption that old CX findings remain current.

The package contains no raw document content, prompt/generation body, database
URL, credential, or local absolute path. Its manifest hash detects mutation.

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_ag_cx_transition_handoff.py \
  --cov=nex_ag.cx_transition_handoff --cov-branch \
  --cov-report=term-missing
```

Observed verification:

```text
focused handoff tests: 9 passed
handoff module statement/branch coverage: 100%
aggregate regression: 6228 passed, 1 known warning
statement=75180/76061=98.841719146475%
branch=17590/18240=96.436403508772%
```
