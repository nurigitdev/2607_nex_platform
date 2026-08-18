# Slice 0315: CX Grounded Response Citation-Quality Boundary Audit

## Scope

Add a CX-owned audit boundary for grounded response citation quality after model
generation and structured draft validation.

This slice does not change database schema, provider configuration, or retrieval
admission behavior. It adds a raw-safe quality audit to the structured draft
validation result and records a small summary on the CX generation execution
record.

## Implemented

- Added `cx_grounded_response_citation_quality_audit.v1`.
- Added `build_grounded_response_citation_quality_audit`.
- Added redaction assertion for raw model output and retrieval source text.
- Added audit status coverage for:
  - citation requirement;
  - citation presence;
  - citation-to-evidence membership;
  - selected evidence citation coverage;
  - raw output redaction.
- Added `validation.quality_audit` to `cx_structured_draft.v1`.
- Added CX generation execution metadata summary:
  - `grounded_response_quality_audit_schema_version`;
  - `grounded_response_quality_status`;
  - `grounded_response_quality_issue_count`.
- Added positive and negative contract coverage for the audit shape.

## Runtime Behavior

CX now builds the audit immediately after structured draft citation validation.
The audit stores hashes, counts, labels, issue codes, stage status, and
recommended action only. It does not store raw generated output, prompt text,
retrieval evidence text, provider endpoints, or secrets.

Generation still completes with a structured draft even if citation validation
fails. The new audit makes that result explicit as `boundary_status=FAIL` so AE
and AG can decide how to display, retry, repair, or block the response in later
slices.

## Evidence

- Targeted draft regression:
  `./.venv/bin/pytest tests/test_nex_cx_drafts.py -q`
- Targeted generation regression:
  `./.venv/bin/pytest tests/test_nex_cx_generation.py -q`
- Contract validation:
  `./.venv/bin/pytest tests/test_contract_validation.py -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`

Observed targeted draft result:

```text
11 passed, 1 warning
```

Observed targeted generation result:

```text
43 passed, 1 warning
```

Observed contract validation result:

```text
21 passed
```

Observed full quality gate:

```text
2165 passed, 1 warning
statement_coverage=98.51% threshold=95.00%
branch_coverage=95.35% threshold=85.00%
contract_validation=pass schemas=50 examples=82 negative_examples=58 openapi=7
```
