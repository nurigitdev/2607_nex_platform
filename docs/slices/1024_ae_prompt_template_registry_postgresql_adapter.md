# Slice 1024: AE Prompt and Template Registry PostgreSQL Adapter

## Goal

Turn the existing AE prompt registry schema into a restart-safe runtime adapter
without adding another table or maintaining a parallel registry model.

## Implementation

- Add `SqlAlchemyAePromptRegistryStore` for templates, explicit versions,
  bindings, and render-event lineage.
- Support SQLite regression and PostgreSQL JSONB using the same repository
  contract.
- Resolve natural-key conflicts so an existing migration-seeded template can be
  adopted without replacing its database UUID.
- Expand AE runtime seeds to separate general answer, grounded answer, document
  summary, and document generation bindings.
- Preserve idempotent seeding, restart reads, deterministic render-event IDs,
  and user-prompt hash-only retention.

## Decisions

- Existing `ae_prompt_templates`, `ae_prompt_template_versions`,
  `ae_prompt_bindings`, and `ae_prompt_render_events` remain canonical.
- No DDL migration or new table is needed.
- Runtime app-factory wiring is deferred to the protected policy API Slice so
  repository construction and API behavior do not land in one oversized change.
- Actual PostgreSQL mutation remains protected until Slice 1030.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_prompt_registry_sqlite.py \
  --coverage-target services/nex-ae-api/nex_ae_api/prompt_persistence.py \
  --coverage-target scripts/smoke/run_ae_prompt_registry_sqlite.py \
  --smoke scripts/smoke/run_ae_prompt_registry_sqlite.py
```

## Observed Evidence

- Slice Gate: `2017 passed` with one known warning.
- Repository statement coverage: `97.85%`.
- Repository branch coverage: `95.59%`.
- Prompt repository statement/branch coverage: `100%`/`100%`.
- SQLite smoke: `6/6`, four bindings, one durable render event, next Slice
  `1025`.
