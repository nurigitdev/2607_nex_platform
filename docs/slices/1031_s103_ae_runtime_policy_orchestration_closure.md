# Slice 1031: S103 AE Runtime Policy Orchestration Closure

## Goal

Close S103 with machine-checkable evidence that AE intent resolution, durable
prompt bindings, exact runtime compatibility, generation-policy composition,
chat lineage, contracts, observability, and actual PostgreSQL behavior agree as
one fail-closed orchestration boundary.

## Closure

- All eight boundary gaps from Slice 1022 are resolved.
- Four canonical execution modes use explicit user-mode precedence and a
  deterministic fallback without accepting arbitrary provider runtime fields.
- Prompt template versions, bindings, and render events are restart-safe in
  the existing AE prompt registry tables.
- Runtime policies require exact active compatibility rules and explicit
  versions; resolved records never depend on a mutable `latest` alias.
- The shared AE-CX compatibility catalog preserves its four legacy rules and
  adds all six S103 canonical execution-mode/template combinations, preventing
  the CX boundary from rejecting resolved AE policy packages.
- The protected policy API and chat runtime persist privacy-safe policy
  snapshots, package hashes, and prompt-render lineage.
- Strict JSON Schemas, AE OpenAPI 1.1, negative privacy fixtures, and
  metadata-only operational events match runtime behavior.
- Protected `nex_ae_test` evidence proves policy resolution, chat execution,
  restart reads, idempotency, events, and synthetic-row cleanup.
- Remote model providers are outside S103 and are not required for closure.

## Verification

```bash
NEX_AE_RUNTIME_POLICY_POSTGRES_SMOKE=1 \
NEX_AE_TEST_DATABASE_URL='<test database URL>' \
scripts/quality/run_quality_gate.sh
```

## Observed Evidence

- Closure: components `10/10`, resolved gaps `8/8`, contract checks `12`,
  PostgreSQL checks `17`, next requirement `S104`.
- Actual PostgreSQL: `nex_ae_user@nex_ae_test`, migration count `23`, scoped
  rows `4/1/1/2`, cleanup remaining `0`.
- AE-CX compatibility: all `6` S103 canonical combinations and `4` legacy
  combinations passed; the traceable OA-AE-CX-MO-AG mock flow passed.
- Slice Gate: `2113 passed`; statement coverage `97.89%`; branch coverage
  `95.65%`; new closure and boundary audit statement/branch coverage
  `100.00%`/`100.00%`.
- Full Gate: `8112 passed`; statement coverage `98.77%`; branch coverage
  `96.79%`; contract validation `96/150/113/7`.
