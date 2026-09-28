# Slice 1032: AE-to-CX Asynchronous Generation Boundary Audit

## Goal

Freeze the S104 ownership, compatibility, persistence, privacy, and quality
boundary before AE adopts the durable CX asynchronous generation lifecycle.

## Findings

- CX already owns durable job admission, polling, cancellation, retry/recovery,
  and restart-safe owner-scoped generation handoff.
- AE chat still invokes only the synchronous CX generation route after policy
  and retrieval resolution.
- AE already persists a `PENDING` chat record and has a JSON generation summary
  suitable for a bounded owner-safe job/handoff projection.
- No AE route currently exposes explicit owner-scoped refresh or cancellation.

## Frozen Decisions

- `generation.execution_strategy` selects `SYNCHRONOUS` or `ASYNCHRONOUS`.
  The default remains `SYNCHRONOUS` for backward compatibility.
- CX owns job execution and private generated content. AE owns the user-facing
  chat interaction and persists only owner-safe job/handoff metadata.
- Existing `ae_chat_interactions.generation_summary` storage is reused; S104
  plans no new table.
- Async admission remains idempotent. A replay joins or returns the existing CX
  lineage instead of creating another generation.
- AE polling is an explicit owner-scoped refresh operation. A background poller
  is outside S104.
- Cancellation delegates to CX. Retry after a terminal block creates a new
  idempotent admission while preserving prior lineage.
- Raw prompts, provider endpoints, credentials, evidence text, and generated
  content never enter AE job projections, events, or logs.
- Actual `nex_ae_test` and `nex_cx_test` integration evidence is required in
  Slice 1040. A remote provider is not required for this integration boundary.

## Slice Plan

1. `1032`: boundary audit.
2. `1033`: AE asynchronous generation contract and state projection.
3. `1034`: AE CX asynchronous lifecycle client.
4. `1035`: durable chat admission and idempotent state wiring.
5. `1036`: owner-scoped poll/refresh API and Checkpoint Gate.
6. `1037`: cancellation, retry, and owner-scope integration.
7. `1038`: workspace activity and metadata-only observability.
8. `1039`: JSON Schema and OpenAPI contract hardening.
9. `1040`: actual AE/CX PostgreSQL integration smoke.
10. `1041`: S104 closure and Full Gate.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_cx_async_generation_boundary_audit.py \
  --coverage-target scripts/smoke/run_ae_cx_async_generation_boundary_audit.py \
  --smoke scripts/smoke/run_ae_cx_async_generation_boundary_audit.py
```

The audit performs no database mutation and no provider call.

## Observed Evidence

- Slice Gate: `2093 passed` with one known warning.
- Repository statement coverage: `97.88%`.
- Repository branch coverage: `95.65%`.
- Boundary runner statement/branch coverage: `100%`/`100%`.
- Contract validation: 96 schemas, 150 positive examples, 113 negative
  examples, and 7 OpenAPI documents.
- Audit result: six foundations, eight open gaps, zero issues, next Slice
  `1033`.
