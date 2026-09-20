# Slice 0897: AG to CX transition handoff package

## Goal

Produce a deterministic, redacted, tamper-evident package that defines what
NeX-CX inherits after NeX-AG service MVP acceptance.

## Handoff

- The manifest is first sealed as an acceptance-independent candidate. It fixes
  the exact CX assets that the acceptance gate evaluates and carries an
  `acceptance_binding_status` of `PENDING`.
- After every blocking gate passes, a separate `BOUND` attestation binds the
  accepted report ID to the sealed manifest hash. This two-stage protocol avoids
  requiring an accepted report to construct evidence needed by that same report.
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

The candidate and attestation contain no raw document content,
prompt/generation body, database URL, credential, or local absolute path. Their
independent hashes detect mutation. Slice 0898 is the canonical runtime proof of
this refined two-stage protocol.

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_ag_cx_transition_handoff.py \
  --cov=nex_ag.cx_transition_handoff --cov-branch \
  --cov-report=term-missing
```

Observed verification:

```text
focused handoff tests: 12 passed
handoff module statement/branch coverage: 100%
aggregate regression: 6228 passed, 1 known warning
statement=75180/76061=98.841719146475%
branch=17590/18240=96.436403508772%
```
