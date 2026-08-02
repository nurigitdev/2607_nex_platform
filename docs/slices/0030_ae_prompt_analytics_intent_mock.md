# Slice 0030 AE Prompt Analytics Intent Mock

Status: Implemented.

Backlog candidate: `S3-010` AE prompt analytics and mock intent classification.

Requirement coverage: `AE-FR-002`, `AE-FR-003`, `TRACE-PLAT-001`.

## Scope

Slice 0030 adds AE prompt analytics foundations:

- Optional chat-route analytics recording for prompt events.
- Deterministic mock intent classification for summary, content management,
  workflow automation, and general knowledge work.
- User task profile aggregation by tenant/user and task category.
- Early automation recommendation signal when repeated categories appear or an
  automation/workflow request is detected.
- Read endpoints for analytics snapshots, task profiles, and recommendations.
- `ae_prompt_analytics.v1` contract with a negative raw prompt leak fixture.

Analytics records store prompt hashes, short previews, counts, categories, and
lineage IDs. They do not store the full raw prompt.

## Files

- `services/nex-ae-api/nex_ae_api/analytics.py`
- `services/nex-ae-api/nex_ae_api/chat.py`
- `services/nex-ae-api/nex_ae_api/main.py`
- `contracts/schemas/service/nex_ae_api/prompt_analytics.v1.schema.json`
- `tests/test_nex_ae_prompt_analytics.py`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

Regression tests cover classifier rules, prompt token estimates, owner scope
validation, chat analytics recording, no-answer analytics recording, profile
aggregation, recommendation creation, endpoint auth/readback, and contract
validation.
