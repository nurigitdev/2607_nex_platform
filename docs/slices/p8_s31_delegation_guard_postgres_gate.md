# P8-S31 Delegation Guard PostgreSQL Acceptance and Full Gate

## Scope

Close P8.2A with protected acceptance against the actual `nex_wc_test`
PostgreSQL database and a repository-wide Full Gate. The acceptance covers the
canonical DG-01 through DG-12 scenarios without requiring any remote model
provider.

## Protected Database Boundary

- URL source: `NEX_WC_TEST_DATABASE_URL`
- required database identity: `nex_wc_test`
- required database user: `nex_wc_user`
- activation flags:
  - `NEX_WC_P8_S28_POSTGRES_SMOKE=1`
  - `NEX_WC_P8_S29_POSTGRES_SMOKE=1`
  - `NEX_WC_P8_S31_POSTGRES_SMOKE=1`
- migration inventory is checked through `1005_wc_assignment_execution`
- each scenario uses a unique tenant and removes every inserted WC row in a
  `finally` block
- all post-cleanup table counts are zero

## Canonical Scenario Coverage

| Scenario | Acceptance evidence |
| --- | --- |
| DG-01 depth 1 creation | S31 protected PostgreSQL depth journey |
| DG-02 depth 10 may execute | S31 protected PostgreSQL depth journey |
| DG-03 depth 10 to child denied | S31 protected PostgreSQL hop-limit denial |
| DG-04 claim does not increase depth | S31 immutable lineage comparison before and after claim |
| DG-05 sixth direct child denied | S28 protected PostgreSQL child-budget smoke |
| DG-06 fifty-first root descendant denied | S29 protected PostgreSQL root-budget smoke |
| DG-07 A to B to A denied at claim | S31 protected PostgreSQL cycle smoke |
| DG-08 stale parent claim denied | S31 protected PostgreSQL stale-generation smoke |
| DG-09 expired parent claim denied | S31 protected PostgreSQL expired-lease smoke |
| DG-10 concurrent creation cannot oversubscribe | S28 same-parent and S29 cross-parent PostgreSQL concurrency smokes |
| DG-11 revoked `work:delegate` denied | S31 protected PostgreSQL authorization smoke |
| DG-12 no guard failure creates child execution | denial residue assertions over WorkItem, Claim, Assignment, and Outbox authority |

## Verification

- S31 protected PostgreSQL core: `3 passed`
- combined S28, S29, and S31 protected PostgreSQL acceptance: `9 passed`
- actual PostgreSQL WC/P7 regression: `309 passed`, `5 protected skips`
- repository Full Gate pytest: `15,931 passed`, `62 skipped`
- statement coverage: `96.87%` (required `95%`)
- branch coverage: `96.26%` (required `85%`)
- contract validation: PASS
  - schemas: `179`
  - examples: `241`
  - negative fixtures: `210`
  - OpenAPI documents: `9`
- Full Gate closure smoke chain: PASS, exit code `0`
- remote embedding, reranker, and generation providers: not required

## Closure

P8.2A is CLOSED. `wc_delegation_lineage` remains the only new persistence
relation introduced by this wave; `wc_work_item`, `wc_claim`, and
`wc_assignment` remain the authoritative existing WC structures reused by the
guard.
