# P8-S41 Approval Detail And Decision API

## WC-Controlled Boundary

WC now exposes display-safe approval detail plus `APPROVE` and `REJECT`
actions. IA remains a presentation and interaction surface; all authoritative
mutation stays inside the WC approval aggregate.

```text
GET  /api/v1/approval-gates/{approval_work_item_id}
POST /api/v1/approval-gates/{approval_work_item_id}/decisions
```

Both routes require a valid `nex-wc` service token and tenant/subject headers.
Detail requires a current OA `approval:read` grant and eligible target match.
Ineligible, absent, or time-expired pending gates are returned as `404` to
avoid disclosing cross-subject work.

## Decision Semantics

The decision route accepts only the canonical
`wc_approval_decision_request.v1` shape and the exact actions `APPROVE` or
`REJECT`.

Every submission, including an exact idempotent replay, performs a fresh OA
`approval:decide` authorization and target compatibility check. A new decision
atomically:

```text
appends wc_approval_decision
advances wc_approval_work_item to APPROVED or REJECTED
appends one wc_approval_outbox event
```

Exact replay returns the existing decision with HTTP `200`; first commit uses
HTTP `201`. A conflicting terminal action or an undecided item that has expired
fails with `409` and leaves no residue.

## Safety

The detail contract contains the safe HumanGateView, creation time, version,
and fixed decision options. It excludes the protected request, semantic hash,
source, resume target, and execution internals.

The API module has no NSL or EOS repository dependency. It cannot directly
mutate an NSL checkpoint or EOS business table; those downstream effects remain
event-consumer responsibilities.

## Verification

- focused S41 tests: `18 passed`
- S40/S41 focused tests after coverage additions: `38 passed`
- cumulative approval tests: `141 passed`
- cumulative approval coverage: `98.71% statement`, `96.63% branch`
- WC/AE integration regression: `443 passed`, `12 protected skips`
- contract validation: `188 schemas`, `250 examples`, `217 negative`,
  `9 OpenAPI` passed
- Ruff checks: passed

Actual WC/OA PostgreSQL and IA UI acceptance remains owned by canonical
P8-S43. P8-S41 is followed by the requested repository Checkpoint Gate.
