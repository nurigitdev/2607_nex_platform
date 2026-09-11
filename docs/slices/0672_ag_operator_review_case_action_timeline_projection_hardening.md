# Slice 0672: AG operator review case action timeline projection hardening

## Intent

Harden the AG operator review case timeline after the S68 boundary audit so
operator-facing lifecycle evidence is easier to read and remains metadata-only.

## Scope

- Keep `GET /admin/v1/operator-review/cases/{case_id}/timeline` as the
  lifecycle timeline surface.
- Keep action history storage `operational_events_first`; no action-history or
  lifecycle table is introduced.
- Add deterministic `sequence` values after timeline sorting.
- Add `timeline_kind` so clients can distinguish case-recorded and action
  events without parsing `event_type`.
- Add `action_outcome` with safe transition facts:
  - action id/type
  - from/to status
  - status transition flag
  - assignment flag
  - resolution flag
  - terminal-action flag
- Add item-level redaction flags proving raw operational-event details are not
  copied into timeline payloads.
- Extend the timeline summary with first event time and action outcome counts.
- Update the canonical JSON Schema and timeline contract examples.

## Decision

- Timeline hardening is read-model-only and reuses existing
  `service_operational_events`.
- `POST /admin/v1/operator-review/cases/{case_id}/actions` remains the
  authoritative mutation route.
- Timeline items expose whitelisted operational-event fields only. Raw case
  comments, action comments, resolution text, raw notes, evidence bodies,
  prompts, source text, provider payloads, local storage paths, database URLs,
  service tokens, idempotency keys, and raw metadata payloads remain excluded.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operator_review_cases.py tests/test_nex_ag_operator_review_cases.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
./.venv/bin/python scripts/quality/validate_contracts.py
./scripts/quality/run_quality_gate.sh
```

## Result

The targeted operator-review case tests cover case-recorded events, assignment
actions, terminal resolution actions, subject-ref-only action events, route
responses, limit behavior, unavailable event stores, and raw payload redaction.
