# P8-S38 Approval Decision Outbox

## Atomic Publication Boundary

WC now commits these mutations in one transaction:

```text
append wc_approval_decision
insert wc_approval_outbox(PENDING)
advance wc_approval_work_item state/version
```

An outbox insert failure rolls back all three. Consumers never observe an
approval event without a durable decision, and a durable decision cannot be
silently stranded without an event.

Exact terminal replay performs fresh authorization but returns the original
decision and creates no second outbox event.

## Domain Mapping

```text
NSL_WRITE       -> NSL_APPROVAL_DECIDED
AGENT_FORMAL    -> AGENT_FORMAL_APPROVAL_DECIDED
BUSINESS_FORMAL -> BUSINESS_FORMAL_APPROVAL_DECIDED
```

The event contains only contract-approved references and metadata-safe OA
evidence. Raw tokens and protected request payloads are never copied into the
outbox.

## Consumer Boundary

Repositories expose a bounded, deterministic pending-event read ordered by
`created_at, outbox_id`. Enqueue/delivery acknowledgement and AE/NSL resume are
later phase responsibilities; P8-S38 establishes the durable producer side.

## Verification

- focused cumulative approval tests: `92 passed`
- cumulative `nex_wc.approvals` coverage: `98% statement/branch`
- WC/P7/P8 regression: `405 passed`, `12 protected skips`
- contract validation: `183 schemas`, `245 examples`, `214 negative`,
  `9 OpenAPI` passed
- one event per decision, all three domain mappings, and no replay duplicate
- forced outbox failure proves transaction rollback and zero residue
- event/outbox negative matrix and bounded deterministic pending read
