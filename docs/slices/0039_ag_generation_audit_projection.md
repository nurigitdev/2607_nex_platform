# Slice 0039 AG Generation Audit Projection

Status: Implemented.

Backlog candidate: `S4-009` AG generation audit projection over CX events and
AE handoffs.

Requirement coverage: `AG-FR-002`, `AG-FR-003`, `AG-FR-005`, `CX-FR-008`,
`AEAPI-FR-004`, `PLAT-FR-005`, `TRACE-GEN-001`.

## Scope

Slice 0039 adds the first read-only AG generation audit surface:

- `ag_generation_audit_event.v1` JSON Schema and fixtures.
- AG HTTP source client for CX generation records, CX progress events, and AE
  artifact handoff records.
- Admin endpoint:
  `/admin/v1/generation-audit/generations/{cx_generation_id}`.
- Optional `artifact_handoff_id` query parameter to include AE handoff lineage.
- Redacted projection of generation summary, provider usage, compatibility
  metadata, quality metadata, ordered progress events, and artifact handoff
  metadata.

AG does not read service databases directly and does not mutate AE, CX, MO, or
OA records. The projection excludes raw prompts, generated output text, source
text, provider URLs, model paths, local storage paths, and token-like secrets.

## Files

- `services/nex-ag/nex_ag/generation_audit.py`
- `services/nex-ag/nex_ag/main.py`
- `contracts/schemas/generation/ag_generation_audit_event.v1.schema.json`
- `tests/test_nex_ag_generation_audit.py`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

Regression tests cover projection assembly, optional artifact handoff omission,
failed-generation status mapping, timeline redaction, route auth/error mapping,
HTTP source reads, HTTP error handling, and contract validation.
