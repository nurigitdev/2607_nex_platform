# Slice 1058: AE Citation Repair Workflow Observability

## Goal

Emit deterministic operational evidence for citation validation, bounded
repair, and attention-required outcomes without exposing owner-private data.

## Implementation

- Added `ae_citation_quality_observability.v1` and the
  `ae.citation_quality.workflow_observed` event.
- Classified workflow outcomes as `CITATION_NOT_REQUIRED`,
  `CITATION_VALIDATED`, `BOUNDED_REPAIR_SUCCEEDED`, or
  `ATTENTION_REQUIRED`.
- Used deterministic event IDs so repeated observation of the same generation
  state does not duplicate operational events.
- Emitted only status, issue counts, repair attempt bounds, and remediation
  requirement metadata.
- Wired emission after durable refresh, progress, recovery, or reconciled
  cancellation updates.

## Privacy And Reliability

- Prompt, response, evidence, invalid output, owner identity, and provider
  details are explicitly excluded.
- Operational event persistence remains non-blocking through `safe_emit`.
- No database migration, PostgreSQL access, or remote provider is required.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_citation_quality_observability.py \
  --test tests/test_ae_async_chat_refresh.py \
  --coverage-target services/nex-ae-api/nex_ae_api/citation_quality_observability.py
```

## Observed Evidence

- Slice Gate: pass (`2402 passed`, `2` separately protected PostgreSQL smoke
  tests skipped).
- Statement coverage: `97.95%` (threshold `95%`).
- Branch coverage: `95.85%` (threshold `94%`).
- `citation_quality_observability.py`: statement `100%`, branch `100%`.
- Contract validation: pass (`100` schemas, `156` positive examples, `119`
  negative examples, `7` OpenAPI documents).
