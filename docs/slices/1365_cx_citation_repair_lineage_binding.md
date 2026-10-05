# Slice 1365: CX Citation Repair Lineage Binding

## Goal

Bind citation validation and the single bounded repair attempt to the exact
owner-admitted retrieval package and selected evidence set through durable CX
persistence, read-model projection, and AE handoff.

## Implementation

- Extracted deterministic grounded evidence binding so prompt assembly and
  citation repair recompute the same selected evidence hash.
- Citation repair now rejects retrieval identity, evidence binding, or selected
  evidence count drift before a second provider request.
- Added strict `cx_grounded_generation_lineage.v1` metadata containing package,
  evidence, citation validation, repair-attempt, and prompt-transition hashes.
- CX execution persistence and read-model projection validate this lineage and
  retain no private evidence or generated text.
- READY generation handoff fails closed when package, evidence count, effective
  prompt hash, or citation repair metadata differs from durable lineage.
- Existing `cx_citation_repair.v1` remains compatible; the stronger lineage is
  a separate projection instead of a breaking repair schema revision.

## Verification

```bash
scripts/quality/run_slice_gate.sh \
  --service nex-cx \
  --test tests/test_cx_grounding_repair_lineage.py \
  --test tests/test_nex_cx_generation_lineage.py \
  --test tests/test_nex_cx_citation_repair.py \
  --test tests/test_nex_cx_generation_handoff.py \
  --test tests/test_nex_cx_async_generation_worker.py \
  --coverage-target scripts/smoke/run_cx_grounding_repair_lineage.py \
  --smoke scripts/smoke/run_cx_grounding_repair_lineage.py
```

This Slice uses deterministic providers and stores. PostgreSQL and live
generation-provider evidence remains assigned to Slice 1370. Slice 1366 may now
persist this validated CX lineage in AE and run the fifth-Slice Checkpoint Gate.

Observed evidence:

- Slice Gate: `2,451 passed`
- repository statement coverage: `99.10%`
- repository branch coverage: `98.23%`
- repair, lineage, handoff, and deterministic evidence targets: `100%`
  statement/branch coverage
- contract validation: `162` schemas, `221` examples, `189` negative
  examples, and `7` OpenAPI documents
- deterministic grounding/repair lineage evidence: `10/10` checks
