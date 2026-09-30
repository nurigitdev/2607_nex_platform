# Slice 1131: S113 MO provider-aware readiness closure

## Goal

Close S113 with machine-checkable boundary, domain, active-probe, cache,
composition, API contract, protected PostgreSQL/DGX, privacy, and quality
evidence.

## Result

- Provider readiness requires embedding, reranking, and generation to be
  READY, in addition to the existing MO database readiness check.
- Live route health comes from active preflight; timeout and upstream failures
  remain distinct from non-retryable configuration/model failures.
- A bounded process-local TTL cache prevents probe amplification, while stale
  evidence always fails readiness closed.
- The authenticated route-health API returns the same privacy-safe cached
  projection governed by canonical JSON Schema and OpenAPI contracts.
- Actual `nex_mo_user@nex_mo_test` and all three current DGX models passed the
  protected Slice 1130 smoke with `8/8` checks.
- S113 added no database table. Durable aggregate telemetry remains S116 scope,
  while bounded retry/resilience is S115 and GPU observability is S117.
- S114 is the next requirement: MO contract and API drift closure.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_s113_mo_provider_readiness_closure.py

./.venv/bin/python \
  scripts/smoke/run_s113_mo_provider_readiness_closure.py --summary

scripts/quality/run_quality_gate.sh
```

## Quality Evidence

- Closure evidence: `8/8`; components: `6/6`; protected live checks: `8`.
- Protected Slice 1130 evidence: actual PostgreSQL test identity and all three
  configured DGX providers passed `8/8` checks with `3/3` current models.
- Full Gate: `9,067 passed`, `5 skipped`, `123 warnings`; statement coverage
  `98.86%`; branch coverage `97.04%`.
- Contract validation: `110` schemas, `168` positive examples, `133` negative
  examples, and `7` OpenAPI documents.
- AE Web Node regression and the complete deterministic smoke/closure sequence
  passed; protected external-resource tests without explicit opt-in were
  skipped by design.
- The first Full Gate detected that the historical S111 audit still required
  exactly five readiness gaps after S113 closed one of them. The S111 closure
  assertion now accepts monotonic gap reduction while still requiring a
  non-zero `GAPS_CONFIRMED` state; the complete Full Gate rerun passed.
