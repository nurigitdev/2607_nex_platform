# Slice 1057: AE Async Citation Workflow Integration

## Goal

Make the privacy-safe citation-quality workflow durable when an asynchronous
CX generation handoff becomes READY.

## Implementation

- Built the canonical citation workflow from the same validated READY handoff
  used by AE asynchronous refresh.
- Persisted the metadata-only workflow in the existing
  `ae_chat_interactions.generation_summary`; no new table was added.
- Preferred the validated persisted workflow on citation-quality reads while
  preserving CX fallback for legacy interactions.
- Carried the same metadata-only workflow through progress and recovery
  terminal-handoff orchestration, not only the explicit refresh route.
- Rejected persisted workflow lineage that does not match the interaction and
  CX generation identifiers.
- Preserved transient response content behavior: AE returns content to the
  owner during refresh but does not persist it.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_async_chat_refresh.py \
  --test tests/test_ae_citation_quality_api.py \
  --coverage-target services/nex-ae-api/nex_ae_api/chat.py
```

The focused tests include a SQLite store restart and verify that a subsequent
citation-quality read uses the durable projection without a second CX call.

## Observed Evidence

- Slice Gate: pass (`2395 passed`, `2` separately protected PostgreSQL smoke
  tests skipped).
- Statement coverage: `97.94%` (threshold `95%`).
- Branch coverage: `95.85%` (threshold `94%`).
- `generation_lifecycle.py`: statement `100%`, branch `100%`.
- `chat.py`: statement `96.77%`, branch `95.67%`.
- Contract validation: pass (`100` schemas, `156` positive examples, `119`
  negative examples, `7` OpenAPI documents).
