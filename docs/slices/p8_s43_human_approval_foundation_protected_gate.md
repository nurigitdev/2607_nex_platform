# P8-S43 Human Approval Foundation Protected Gate

**Status:** PASS  
**Date:** 2026-10-22

## Scope

P8-S43 closes the P8.3 Human Approval Foundation against the actual
`nex_oa_test` and `nex_wc_test` PostgreSQL databases and an authenticated IA
browser surface. It does not change a production table, migration, approval
contract, or product route.

The protected path is:

```text
employee credential login
-> AE browser session facade
-> AE approval facade
-> WC approval inbox/detail/decision API
-> fresh OA effective authorization
-> WC immutable decision and durable outbox
```

Remote embedding, reranking, and generation providers are not part of this
gate.

## Database Boundary

- OA URL source: `NEX_OA_TEST_DATABASE_URL`
- WC URL source: `NEX_WC_TEST_DATABASE_URL`
- required identities:
  - `nex_oa_user` / `nex_oa_test`
  - `nex_wc_user` / `nex_wc_test`
- activation flag: `NEX_P8_S43_APPROVAL_POSTGRES_SMOKE=1`
- both migration inventories are applied and verified before execution
- WC approval fixtures and OA identity/session fixtures are removed in
  dependency order after every protected scenario
- post-cleanup row counts are zero

## Protected Approval Coverage

The P8.3 exit boundary owns ApprovalWorkItem persistence, IA pending inbox,
fresh OA `approval:read` and `approval:decide`, target validation,
Approve/Reject, duplicate/conflict behavior, and `BUSINESS_FORMAL` domain
support.

| Canonical scenario | P8-S43 evidence |
| --- | --- |
| AP-03 duplicate ApprovalRequestId idempotent | actual WC create-or-get returns the same work item |
| AP-04 same identity with changed semantics conflicts | changed semantic hash is rejected with no duplicate row |
| AP-05 inactive approver denied | actual inactive OA membership returns a WC authorization denial |
| AP-06 missing `approval:decide` denied | actual OA read-only membership creates no decision or outbox |
| AP-07 target mismatch denied | fully authorized but non-target principal is denied |
| AP-08 OA unavailable fails closed | unavailable OA source returns retryable `503` with zero mutation |
| AP-09 approve creates one immutable decision | actual WC decision and outbox counts are exactly one |
| AP-10 exact approve replay is idempotent | replay returns the existing decision and HTTP `200` in IA |
| AP-11 approve then reject conflicts | conflicting terminal action returns `409` |
| AP-17 expired approval requires reapproval | expired item is non-actionable and decision is rejected |

AP-01, AP-02, AP-12 through AP-16, and AP-18 require AE wait/resume or EOS
WRITE behavior and remain assigned to later P8.4/P8.5 slices. P8-S43 does not
claim them early.

## Authenticated IA Acceptance

The new fetch-mode Playwright runner proves that:

- approval data is absent from the anonymous surface;
- employee credential login creates an actual OA PostgreSQL session;
- the IA inbox contains only the two eligible, non-expired gates;
- `NSL_WRITE` and `BUSINESS_FORMAL` remain visibly distinct;
- approve and reject traverse the AE and WC HTTP boundaries;
- exact approve replay returns `200` without another decision or outbox row;
- a target-mismatched gate and an expired gate both remain hidden as `404`;
- logout returns immediately to the authentication shell; and
- protected request, semantic hash, source, resume target, service token, and
  storage details never enter browser evidence.

The product-facing command is:

```text
npm --prefix apps/nex-ae-web run smoke:approval-protected-playwright
```

It is normally launched by the protected PostgreSQL pytest harness because the
harness owns fixture creation, service startup, database observation, and
zero-residue cleanup.

## Full Gate Reconciliation

The first repository Full Gate detected that the S42 AE approval facade had
added a new loopback client without updating the current deployment-coupling
inventory. Source inspection also found that its fallback URL used the NeX-EOS
port (`8107`) instead of the registered NeX-WC port (`8106`). The fallback is
now defined once from `SERVICE_SPECS["nex-wc"].default_port`, and the current
coupling baseline is reconciled from `46/26` to `47/27` occurrences/files.
Historical Slice evidence remains historical; the active production-readiness
plan and re-audit now describe the current repository.

## Verification

- actual OA/WC PostgreSQL and authenticated IA protected gate: `3 passed`
- protected browser checks: `12/12`
- persisted browser journey:
  - work items: `4`
  - immutable decisions: `2`
  - durable outbox rows: `2`
  - exact replay duplicates: `0`
- cumulative P8 approval regression: `197 passed`, `2 protected skips`
- focused approval Python coverage: `99%` combined
  - AE approval facade: `100%`
  - WC approval API: `100%`
  - WC approval domain/persistence: `98%`
- AE Web Node regression: `355 passed`
- repository Full Gate: PASS
  - Python: `16129 passed`, `64 protected skips`
  - statement coverage: `96.88%`
  - branch coverage: `96.27%`
  - contracts: `188` schemas, `250` examples, `217` negative examples,
    `9` OpenAPI documents
  - AE Web Node: `355 passed`, `0 failed`

## Closure

P8.3 is CLOSED. WC remains the approval lifecycle and decision system of
record, OA remains the current authorization authority, and IA remains a
display-safe interaction channel. NSL suspend/resume is intentionally deferred
to P8.4.
