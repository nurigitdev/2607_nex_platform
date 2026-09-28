# Slice 1041: S104 AE-to-CX Asynchronous Generation Closure

## Goal

Close S104 with machine-checkable evidence that AE asynchronous chat and the CX
durable generation lifecycle form one owner-scoped, restart-safe, privacy-aware
integration boundary.

## Closure

- `generation.execution_strategy` explicitly selects async execution while the
  backward-compatible default remains synchronous.
- CX owns durable jobs, private generation requests, worker execution, private
  output, cancellation, recovery, and handoff.
- AE owns chat interactions and stores only safe job/handoff projections in the
  existing `generation_summary`; S104 adds no database table.
- Explicit owner-scoped refresh returns hash-verified generated content only in
  the response and never persists that content in AE.
- Cancellation and retry preserve owner isolation, idempotency, input-hash
  binding, and safe parent lineage.
- Workspace activity and operational events expose lifecycle metadata without
  prompt, response, owner, provider, or credential material.
- JSON Schemas, privacy fixtures, and AE OpenAPI 1.2 match the implemented
  admission, refresh, cancel, and retry APIs.
- The S103 contract-observability baseline now rejects contract-count or
  OpenAPI-version regressions while allowing additive S104 contract growth.
- Actual `nex_ae_test` and `nex_cx_test` evidence proves migrations, writes,
  worker execution, handoff, restart reads, owner isolation, and zero residue.
- Remote model providers remain outside the S104 persistence and integration
  boundary; the PostgreSQL smoke uses a deterministic mock provider.

## Verification

```bash
NEX_AE_CX_ASYNC_POSTGRES_SMOKE=1 \
NEX_AE_TEST_DATABASE_URL='<AE test database URL>' \
NEX_CX_TEST_DATABASE_URL='<CX test database URL>' \
./.venv/bin/python scripts/smoke/run_s104_ae_cx_async_generation_closure.py --summary

scripts/quality/run_quality_gate.sh
```

## Observed Evidence

- Actual PostgreSQL integration: PASS, 17/17 checks, AE/CX cleanup residue
  `0/0`.
- Database identities: `nex_ae_user@nex_ae_test` and
  `nex_cx_user@nex_cx_test`; migrations were current at `23/23` and `21/21`.
- Lifecycle evidence: admission, CX worker execution, handoff, AE refresh,
  restart reads, owner isolation, and cleanup all passed.
- Contract tree: 98 schemas, 153 positive examples, 116 negative examples, and
  7 OpenAPI documents.
- S104 closure: PASS (`10/10` components, `8/8` gaps), next requirement S105.
- Full Gate: PASS (`8251 passed`, `1` protected PostgreSQL smoke skipped);
  statement coverage `98.80%`, branch coverage `96.80%`.
