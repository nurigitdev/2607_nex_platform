# W60-S7-03A Protected E2E, Rebuild, Performance, and W60 Closure

## Status

- Slice: `W60-S7-03A`
- Status: `IMPLEMENTED_AND_VERIFIED`
- Date: 2026-11-15
- Owners: NeX-OA, NeX-EOS, NeX-MyBee
- W60 status: `CLOSED`

## Decision

W60 closes on the persisted Project P&L boundary delivered by S7-02 through
S7-03. The closure reuses the existing EOS projection, privacy, payroll,
material, and OA entitlement authorities. It does not add another read model,
database table, or remote model-provider dependency.

Protected acceptance uses the actual `nex_eos_test` and `nex_oa_test`
PostgreSQL databases. Every P&L read is admitted through the dedicated
`project:pnl:read` action, the persisted privacy guard, and the strict MyBee
consumer. The test workload uses bounded samples to detect regressions; its
budgets are acceptance guardrails and are not a production SLO commitment.

## Closure Matrix

The executable closure runner covers eight actual PostgreSQL paths:

1. direct and allocation projection rebuild;
2. payroll posting and labor-effort evidence bridge;
3. payroll allocation, residual labor, and adjustment replay;
4. material commitment attribution;
5. material consumption release and cost reconciliation;
6. authorized Project P&L query and MyBee admission;
7. payroll privacy replay and zero-residue cleanup;
8. OA Project entitlement restart and authorization decision.

The runner fails closed unless its database URLs identify `nex_eos_test` and
`nex_oa_test`. Remote embedding, reranking, and generation providers are not
part of this boundary.

## Restart, Rebuild, and Performance Evidence

The payroll-to-P&L protected journey creates 20 immutable projection versions,
disposes and recreates the SQLAlchemy engine/session boundary, and exact-replays
the latest rebuild after restart. It then performs 50 concurrent authorized
reads against persisted evidence and verifies the canonical lookup index with
`EXPLAIN (FORMAT JSON)`.

Observed actual PostgreSQL results:

```text
rebuild_samples=20
rebuild_p95_ms=14.752
rebuild_p95_budget_ms=30000.000
restart_rebuild_exact_replay=true
read_samples=50
read_concurrency=50
read_p95_ms=230.027
read_p95_budget_ms=2000.000
projection_index=ix_eos_project_pnl_lookup
zero_residue=true
```

Evidence:

- `reports/quality/mybee_phase1_w60_s7_03a_closure.json`
- `reports/quality/mybee_phase1_w60_s7_03a_performance.json`

## Baseline Reconciliation

Migration `2548_eos_pnl_privacy_guard.sql` and the S7-03 EOS OpenAPI changes
are now reflected in the MyBee source manifest and compatibility lock. The
baseline tests compare those records with the actual repository inventory and
content hashes; they do not introduce a second migration authority.

The MyBee consumer regression now imports its shared Project P&L fixture from
the repository test root explicitly, so service-specific import-path injection
is no longer required during Repository Full Gate collection.

## Verification

Actual PostgreSQL closure runner:

```text
8 passed
databases=nex_eos_test,nex_oa_test
elapsed_seconds=26.988
```

NeX-EOS Slice Gate, including a second protected PostgreSQL execution:

```text
2246 passed, 65 skipped
statement_coverage=97.03% (threshold 95.00%)
branch_coverage=95.30% (threshold 94.00%)
closure_runner_statement_coverage=98.86%
closure_runner_branch_coverage=96.15%
contract_validation=pass schemas=264 examples=315 negative_examples=257 openapi=10
commands=7/7
```

Repository Full Gate:

```text
22422 passed, 179 skipped
statement_coverage=96.75% (threshold 96.00%)
branch_coverage=95.90% (threshold 94.00%)
product_coverage=98.47% statement / 97.03% branch
harness_coverage=94.19% statement / 92.97% branch
contract_validation=pass schemas=264 examples=315 negative_examples=257 openapi=10
canonical_generation_provider_binding=pass model=Qwen3.5-9B port=9111
full_web_acceptance_v2=pass journeys=6 checks=71 screenshots=16
```

The existing non-blocking Starlette/httpx deprecation and frontend bundler
module-directive warnings remain. They are not caused by W60 and do not alter
the acceptance result.

## Handoff

W60 is closed for the current Project P&L scope. Company/NVT rollups, richer
HR/payroll source adapters, full procurement/inventory operations, and BOM
cost attribution remain later-wave work. Future work must preserve immutable
GL lineage, append-only management projections, fresh OA authorization, and
aggregate payroll privacy.
