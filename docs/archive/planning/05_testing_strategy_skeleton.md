# Testing Strategy Skeleton

Status: Draft bootstrap.

Testing should preserve the NeX-PCX discipline: small slices, focused test
additions, regression runs, coverage reporting, and evidence artifacts for live
provider checks. The detailed MVP testing strategy is now assembled in
[Testing Strategy v0.1 Detail](../../34_testing_strategy_v0_1_detail.md).

## Test Layers

| Layer | Scope |
| --- | --- |
| Unit | Pure functions, contracts, tokenizers, ranking math, prompt packaging, validators. |
| Repository integration | Database migrations, repositories, transaction behavior, duplicate detection, freshness checks. |
| API integration | FastAPI endpoints, auth claims, service clients, error envelopes, pagination, filters. |
| Worker integration | Ingestion, extraction, chunking, embedding, BM25 refresh, retries, stale lease recovery. |
| Contract | Embedding, reranker, vLLM, extraction provider, auth claim, and service-to-service API contracts. |
| UI | Playwright flows for user, operator, and admin scenarios with Korean default screenshots. |
| Smoke | Remote DGX provider health/request checks and startup/shutdown evidence. |
| Regression | Full suite with coverage and branch coverage thresholds. |
| Generation acceptance | Mock-first AE/CX/MO/AG end-to-end scenarios for retrieval-grounded generation, artifacts, recovery, and audit. |

## Coverage Gate

Use one pytest invocation for regression and coverage whenever possible:

```bash
NEX_PCX_TEST_DATABASE_URL="postgresql://nex_pcx_test:<password>@127.0.0.1:5432/nex_pcx_test" \
  bash scripts/quality_gate.sh
```

The gate should report:

- Statement coverage percentage.
- Branch coverage percentage.
- Regression test result.
- Threshold failure reason, if any.

## Branch Coverage Focus

Add tests for:

- No-answer and low-confidence search paths.
- Provider timeout, unhealthy, disabled, and mock-mode branches.
- Permission allowed/denied/partial-scope behavior.
- Retry, stale lease, duplicate run, and queue drain guardrails.
- Template completeness, rollback, and active-version selection.
- Generation citation guardrail branches.
- Generation progress, compatibility mismatch, recovery lineage, artifact
  download permission, and AG redaction branches.
- Optional tokenizer/provider dependency unavailable branches.

## Evidence Expectations

| Evidence | When Required |
| --- | --- |
| Playwright screenshot | Any user-visible UI change. |
| Migration revision output | Any schema change. |
| Smoke markdown | Any live remote provider check. |
| Coverage summary | Every committed slice. |
| Operational snapshot | Startup/shutdown/readiness/provider resource slices. |
| Generation E2E evidence | Generation acceptance and contract test implementation slices. |

## Test Data Rules

- Keep deterministic fixtures for document extraction and retrieval.
- Keep large or private source documents outside the repo unless sanitized.
- Store only small text snapshots needed for repeatable tests.
- Separate mock provider fixtures from live DGX smoke evidence.
