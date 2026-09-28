# Slice 1062: AE Generated Response and Chat Lineage Boundary Audit

## Goal

Freeze the S107 response ownership, private storage, chat lineage, owner scope,
privacy, and quality boundary before AE begins to retain the owner-visible
content returned by a successful CX generation handoff.

## Findings

- CX already exposes integrity-checked owner-private content through a READY
  generation handoff and remains the source owner for generation execution.
- AE validates and returns that content from async refresh, but the current
  contract explicitly records `content_persisted_by_ae: false`.
- AE already persists chat metadata, runtime policy, retrieval, citation,
  retry, artifact, workspace activity, and operational-event lineage.
- AE has no private generated-response storage adapter, canonical response
  lineage projection, restart-safe response read, or owner-scoped response API.

## Frozen Decisions

- CX owns source generation content and execution lineage. AE owns the durable
  user-facing chat response and its owner-scoped lineage projection.
- Raw response content stays outside PostgreSQL. AE stores it behind a logical
  `ae://chat-responses/...` reference, with the configurable local root
  `NEX_AE_CHAT_RESPONSE_STORAGE_ROOT` and the recommended operating path
  `/data/nex-platform/ae/chat-responses`.
- Existing `ae_chat_interactions.generation_summary` stores only safe response
  metadata and lineage; no new database table is planned.
- Public APIs never expose a filesystem path or storage reference. Content is
  loaded only after exact tenant and owner authorization and hash verification.
- The idempotency identity is interaction ID, CX generation ID, and content
  SHA-256. Retry lineage links parent interaction/response while bounded inline
  citation repair remains the final content of the same CX generation.
- Operational events and workspace activity remain metadata-only.
- Slice 1070 must use the actual `nex_ae_test` and `nex_cx_test` databases.
  Remote providers are not required because a deterministic CX handoff can
  prove this integration boundary.

## Slice Plan

1. `1062`: boundary audit and refactoring checkpoint.
2. `1063`: AE private generated-response storage adapter.
3. `1064`: canonical chat response lineage projection and persistence.
4. `1065`: exact-owner generated-response read API.
5. `1066`: async READY handoff integration and Checkpoint Gate.
6. `1067`: retry and bounded-repair lineage hardening.
7. `1068`: metadata-only activity and observability.
8. `1069`: JSON Schema and OpenAPI hardening.
9. `1070`: actual AE/CX PostgreSQL and private-storage smoke.
10. `1071`: S107 closure and Full Gate.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_generated_response_lineage_boundary_audit.py \
  --coverage-target scripts/smoke/run_ae_generated_response_lineage_boundary_audit.py \
  --smoke scripts/smoke/run_ae_generated_response_lineage_boundary_audit.py
```

The audit performs no database mutation, filesystem payload write, or provider
call.

## Observed Evidence

- Slice Gate: `2420 passed`, `3 skipped` protected PostgreSQL tests.
- Coverage: statement `97.95%`, branch `95.86%`.
- Boundary runner coverage: statement `100.00%`, branch `100.00%`.
- Contracts: schemas `101`, examples `159`, negative examples `122`,
  OpenAPI documents `7`.
- Audit: foundations `7`, gaps `8`, open `8`, issues `0`, next `1063`.
