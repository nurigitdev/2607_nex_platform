# Slice 1093: AE MVP Acceptance Policy

## Goal

Freeze one validated policy for deciding whether the combined NeX-AE API and
Web service MVP is accepted and ready for operations handoff.

## Blocking Gates

1. S101-S109 requirement closures.
2. Contract validation.
3. Unit and aggregate regression.
4. Statement coverage.
5. Branch coverage.
6. Actual `nex_ae_test` and `nex_cx_test` PostgreSQL smoke.
7. Live grounded generation through embedding, reranking, and generation.
8. Privacy, failure, and recovery runbooks.
9. A sealed operations handoff package.

Every gate requires `PASS`; `SKIPPED` never satisfies a required gate.

## Defaults

| Variable | Default | Bounds |
| --- | ---: | ---: |
| `NEX_AE_MVP_MIN_STATEMENT_COVERAGE` | `98.0` | `95.0` to `100.0` |
| `NEX_AE_MVP_MIN_BRANCH_COVERAGE` | `96.0` | `85.0` to `100.0` |
| `NEX_AE_MVP_EVIDENCE_MAX_AGE_HOURS` | `24` | `1` to `168` |
| `NEX_AE_MVP_REQUIRED_REGRESSION_TESTS` | `8500` | `1` to `1000000` |

The live model identities are `Qwen3-Embedding-4B`,
`Qwen3-Reranker-4B`, and `Qwen3.5-4B`. The browser must reach
`VERIFIED_RESPONSE` without receiving a server secret header.

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_ae_mvp_acceptance.py \
  --cov=nex_ae_api.mvp_acceptance --cov-branch --cov-report=term-missing
```

No table or migration is added. Production release, deployment, IdP, object
storage, distributed load, and disaster-recovery certifications remain
advisory deferrals outside this service MVP acceptance.
