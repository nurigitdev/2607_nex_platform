# Slice 1042: AE Generation Lifecycle Boundary Audit

## Goal

Freeze the S105 progress, cancellation, recovery, ownership, persistence,
privacy, and quality boundary before extending the S104 asynchronous chat
integration.

## Findings

- CX already owns durable asynchronous jobs, worker execution, cancellation,
  recovery, private output, and handoff.
- AE already owns owner-scoped chat admission, explicit refresh, cancellation,
  retry, durable lifecycle metadata, and workspace activity.
- The canonical CX generation progress event contract exists, but AE has no
  dedicated privacy-safe progress projection or progress route.
- AE cancellation delegates to CX but does not yet reconcile a terminal state
  that wins a cancellation race.
- AE retry validates terminal state and input hash but has no read-only recovery
  plan that a client can inspect before creating a child interaction.

## Frozen Decisions

- CX remains the durable lifecycle authority; AE remains the user-facing chat
  interaction authority.
- Progress is explicit owner-scoped polling. S105 does not add a background
  poller or server-sent event stream.
- AE persists only privacy-safe lifecycle metadata in the existing
  `generation_summary`; no new table is planned.
- Terminal CX state wins cancellation races. AE reconciles before returning a
  conflict or successful terminal projection.
- Recovery is a read-only plan followed by an explicit new child admission.
  Parent input hash and lineage remain mandatory.
- Progress and recovery projections exclude generated content, raw prompts,
  raw failure details, provider endpoints, credentials, and private evidence.
- Actual `nex_ae_test` and `nex_cx_test` evidence is required in Slice 1050.
  Remote providers are outside this orchestration boundary.

## Slice Plan

1. `1042`: boundary audit and refactoring checkpoint.
2. `1043`: privacy-safe progress and recovery projection contract.
3. `1044`: AE generation lifecycle orchestration service.
4. `1045`: owner-scoped progress API.
5. `1046`: cancellation race convergence and Checkpoint Gate.
6. `1047`: recovery plan and retry orchestration.
7. `1048`: workspace activity and metadata-only observability.
8. `1049`: JSON Schema and OpenAPI contract hardening.
9. `1050`: actual AE/CX PostgreSQL lifecycle smoke.
10. `1051`: S105 closure and Full Gate.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_generation_lifecycle_boundary_audit.py \
  --coverage-target scripts/smoke/run_ae_generation_lifecycle_boundary_audit.py \
  --smoke scripts/smoke/run_ae_generation_lifecycle_boundary_audit.py
```

The audit performs no database mutation and no provider call.

## Observed Evidence

- Slice Gate: PASS (`2225 passed`, `1` protected PostgreSQL smoke skipped).
- Repository statement coverage: `97.90%`.
- Repository branch coverage: `95.72%`.
- Boundary runner statement/branch coverage: `100.00%`/`100.00%`.
- Contract validation: 98 schemas, 153 positive examples, 116 negative
  examples, and 7 OpenAPI documents.
- Audit result: seven foundations, eight open gaps, zero issues, next Slice
  `1043`.
