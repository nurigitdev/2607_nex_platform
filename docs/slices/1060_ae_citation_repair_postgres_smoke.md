# Slice 1060: AE Citation Repair PostgreSQL Smoke

## Goal

Prove the S106 grounded citation-repair workflow against the actual
`nex_ae_test` and `nex_cx_test` PostgreSQL databases without depending on a
remote model provider.

## Implementation

- Added an opt-in protected smoke runner guarded by
  `NEX_AE_CITATION_REPAIR_POSTGRES_SMOKE=1`.
- Restricted write execution to the `nex_ae_user@nex_ae_test` and
  `nex_cx_user@nex_cx_test` targets and ran both service migrations first.
- Admitted an owner-scoped grounded AE chat request through the real CX async
  job API and PostgreSQL job/execution repositories.
- Used a deterministic provider that returns one uncited response followed by
  a valid `[1]` response, proving the one-attempt, same-retrieval-package repair
  boundary.
- Verified persisted CX repair metadata, the durable AE `REPAIRED` workflow,
  metadata-only observability, owner isolation before CX lookup, restart reads,
  transient private content, and complete probe cleanup.

## Verification

```bash
NEX_AE_CITATION_REPAIR_POSTGRES_SMOKE=1 \
NEX_AE_TEST_DATABASE_URL='postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test' \
NEX_CX_TEST_DATABASE_URL='postgresql+psycopg://nex_cx_user:***@127.0.0.1:5432/nex_cx_test' \
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_citation_repair_postgres_smoke.py \
  --coverage-target scripts/smoke/run_ae_citation_repair_postgres_smoke.py \
  --smoke scripts/smoke/run_ae_citation_repair_postgres_smoke.py
```

Remote embedding, reranking, and generation providers are not required because
this Slice verifies deterministic citation repair, persistence, and handoff
semantics rather than provider connectivity.

## Observed Evidence

- Slice Gate: pass (`2416 passed`, `2` separately protected PostgreSQL smoke
  tests skipped).
- Statement coverage: `97.95%` (threshold `95%`).
- Branch coverage: `95.85%` (threshold `94%`).
- New protected runner coverage: statement `98.52%`, branch `95.45%`.
- Actual PostgreSQL evidence: `nex_ae_test` and `nex_cx_test`, `18/18`
  checks, two deterministic provider calls, and `0/0` AE/CX probe residue.
- Contract validation: pass (`101` schemas, `159` positive examples, `122`
  negative examples, `7` OpenAPI documents).
