# Slice 0321: AG Generation Audit Grounded Quality Gap Audit

## Scope

Add an AG-owned checkpoint for grounded response quality audit coverage before
wiring it into the operator-facing generation audit projection.

This slice does not change database schema, provider configuration, external
route behavior, or PostgreSQL smoke behavior. It adds a raw-safe helper that
inspects CX generation quality metadata and AE artifact handoff quality summary
coverage.

## Implemented

- Added `ag_generation_audit_grounded_response_quality_gap_audit.v1`.
- Added `build_grounded_response_quality_gap_audit`.
- Captured CX source coverage for:
  - `grounded_response_quality_audit_schema_version`;
  - `grounded_response_quality_status`;
  - `grounded_response_quality_issue_count`.
- Captured AE artifact handoff quality summary coverage for citation status,
  grounding requirement, retrieval package lineage, and evidence reference
  count.
- Added lineage mismatch checks for retrieval package ID/hash,
  `structured_draft_id`, and grounding requirement.
- Added raw-safe redaction summary assertions for prompt text, generated output,
  evidence/source text, provider endpoints, model paths, storage paths, and
  secrets.

## Runtime Behavior

The new helper is internal to AG for this slice. It produces a compact
checkpoint with `coverage_status`, `source_quality_status`, source summaries,
issue codes, recommended action, and `next_guard_slot`.

`PASS` means AG has enough redacted quality metadata to project the status.
`WARN` means a source field or lineage link is incomplete. `FAIL` means the CX
grounded response quality boundary itself reported failure. `NOT_REQUIRED`
means the generation was not grounded.

Recommended next slice:

```text
Slice 0322: AG generation audit quality projection wiring
```

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_ag_generation_audit.py -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`

Observed targeted result:

```text
16 passed, 1 warning
```

Observed full quality gate:

```text
2193 passed, 1 warning
statement_coverage=98.53% threshold=95.00%
branch_coverage=95.42% threshold=85.00%
contract_validation=pass schemas=50 examples=82 negative_examples=59 openapi=7
```
