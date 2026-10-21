# P8-S37 Immutable Approval Decision

## Transaction Rule

WC commits one append-only `wc_approval_decision` row and advances the related
`wc_approval_work_item` projection in the same transaction:

```text
PENDING + APPROVE -> APPROVED
PENDING + REJECT  -> REJECTED
version N         -> version N + 1
```

The SQL path locks the WorkItem row on PostgreSQL and also checks the expected
version during update. The decision row is never updated or deleted.

## Replay Rule

Every replay first performs the fresh P8-S36 OA decision authorization.

- same WorkItem, decision, approver, and comment: return the original decision
  with `created=false`
- opposite decision, different approver, or different comment: deterministic
  `409`, preserving the original decision and terminal WorkItem state
- missing, stale, non-PENDING, or persistence-inconsistent item: fail closed

Candidate decision UUID, current authorization timestamp, and current OA
revision cannot replace historical authority evidence on an exact replay.

## Verification

- focused cumulative approval tests: `69 passed`
- cumulative `nex_wc.approvals` coverage: `98% statement/branch`
- WC/P7/P8 regression: `382 passed`, `12 protected skips`
- contract validation: `183 schemas`, `245 examples`, `214 negative`,
  `9 OpenAPI` passed
- in-memory APPROVE/REJECT state transitions and exact replay
- SQLite restart, one-row append-only history, stale/non-PENDING conflict,
  negative contract matrix, and store failure
