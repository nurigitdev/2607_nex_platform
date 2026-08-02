# Slice 0020 Grounded Traceable Mock Flow

Status: Implemented.

Backlog candidate: `S2-010` Grounded traceable mock flow regression.

Requirement coverage: `TRACE-PLAT-001`, `CX-FR-001` through `CX-FR-006`,
`AE-RETRIEVAL-001`, `AE-CX-001`, `MO-FR-004`, `AG-FR-001`.

## Scope

Slice 0020 expands the original in-process smoke into a deterministic grounded
flow:

- CX registers a mock uploaded Markdown document with source text.
- CX runs text extraction, `chunk_1000_100` chunking, embedding index creation,
  lexical index creation, and retrieval package creation.
- MO serves both mock embedding and mock generation calls through service-token
  protected routes.
- AE chat asks CX retrieval for grounded evidence, then calls CX generation with
  that evidence attached.
- AG readiness projection remains in the same trace evidence bundle.
- The smoke evidence asserts trace propagation and lineage across upload,
  extraction, chunking, embedding, lexical indexing, retrieval, AE chat, CX
  generation, MO generation, and AG readiness.

The script still runs fully in-process with FastAPI `TestClient`; it does not
require DGX-spark, live model files, or a running local service cluster.

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

The summary line now includes document and retrieval package identifiers in
addition to AE/CX/MO/AG IDs:

```bash
traceable_mock_flow=pass trace_id=... doc=... retrieval=... ae=... cx=... mo=... ag_services=5
```

Regression tests verify the expanded trace assertions, retrieval lineage, chunk
and index lineage, MO embedding usage, summary output, output-file evidence, and
mismatch failure behavior.
