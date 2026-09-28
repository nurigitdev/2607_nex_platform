# Slice 1052: AE Citation-Quality and Repair Workflow Boundary Audit

## Goal

Freeze the S106 ownership, repair-mode, persistence, privacy, and quality
boundary before connecting current CX bounded citation repair to the latest AE
asynchronous generation lifecycle.

## Findings

- CX already validates grounded citations and performs at most one bounded
  citation repair with the same admitted retrieval package.
- The CX worker returns a safe repair projection, but it is not persisted in
  the generation read model, so AE cannot explain whether repair occurred.
- AE already maps synchronous generation quality metadata, but asynchronous
  refresh drops the generation quality metadata returned by the CX handoff.
- AE has durable repaired-response handoff/review/decision tables from the
  operator remediation workflow, but legacy read routes are not yet filtered
  by the authenticated tenant and owner.
- AE has no canonical owner-scoped citation-quality workflow projection or
  dedicated inspection route.

## Frozen Decisions

- CX owns generation citation validation and bounded inline repair. AE owns
  the user-facing workflow projection. AG continues to own operator-triggered
  remediation.
- Bounded inline repair and AG/CX remediation repair remain distinct:
  bounded repair is one attempt inside the same generation execution, while
  remediation creates separate lineage and a repaired-response handoff.
- AE persists only privacy-safe citation and repair metadata in the existing
  chat `generation_summary`; no new table is planned.
- Existing repaired-response handoff and decision tables are reused and their
  routes are hardened to exact tenant/owner scope.
- Raw generated or invalid output, prompt text, evidence text, provider
  details, credentials, and local storage paths are excluded.
- Actual `nex_ae_test` and `nex_cx_test` evidence is required in Slice 1060.
  Remote model providers are outside this metadata workflow boundary.

## Slice Plan

1. `1052`: boundary audit and refactoring checkpoint.
2. `1053`: persist safe CX citation repair metadata in the generation read model.
3. `1054`: canonical AE citation-quality workflow projection.
4. `1055`: owner-scoped AE citation-quality workflow API.
5. `1056`: repaired-response owner-scope hardening and Checkpoint Gate.
6. `1057`: async handoff workflow persistence integration.
7. `1058`: metadata-only workflow observability.
8. `1059`: JSON Schema and OpenAPI contract hardening.
9. `1060`: actual AE/CX PostgreSQL workflow smoke.
10. `1061`: S106 closure and Full Gate.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_citation_repair_workflow_boundary_audit.py \
  --coverage-target scripts/smoke/run_ae_citation_repair_workflow_boundary_audit.py \
  --smoke scripts/smoke/run_ae_citation_repair_workflow_boundary_audit.py
```

The audit performs no database mutation and no provider call.

## Observed Evidence

- Slice Gate: PASS (`2330 passed`, `2` separately protected PostgreSQL smoke
  tests skipped).
- Repository statement coverage: `97.91%`.
- Repository branch coverage: `95.77%`.
- Boundary runner statement/branch coverage: `100.00%`/`100.00%`.
- Contract validation: 100 schemas, 156 positive examples, 119 negative
  examples, and 7 OpenAPI documents.
- Audit result: eight foundations, eight open gaps, zero issues, next Slice
  `1053`.
