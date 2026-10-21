# P8-S33 WC ApprovalWorkItem Persistence

## Scope

P8-S33 introduces WC-owned durable persistence for human approvals without
changing the existing delegation, Claim, or Assignment aggregate.

The new relations are:

- `wc_approval_work_item`: actionable human task and exact resume bindings
- `wc_approval_decision`: append-only decision history reserved for P8-S37
- `wc_approval_outbox`: durable publication boundary reserved for P8-S38

The tables deliberately remain separate from `wc_work_item`, `wc_claim`, and
`wc_assignment`. Agent delegation leases and human approval decisions have
different state machines, authority checks, and retry semantics.

## Runtime Boundary

`nex_wc.approvals` provides contract validation plus in-memory and SQLAlchemy
`insert/get` repositories. This Slice does not implement idempotent
`create_or_get`, decision authorization, terminal decision mutation, or outbox
publication. Those responsibilities remain assigned to P8-S34 and P8-S36 to
P8-S38.

Approval source identity is protected by the database uniqueness key:

```text
(tenant_id, approval_domain, source_ref)
```

No raw bearer token or access token is persisted. OA decision evidence columns
are present on `wc_approval_decision` for the later decision commit Slice.

## Verification

- focused unit and SQLite repository regression: `24 passed`
- new module coverage: `100% statement`, `100% branch`
- existing WC/P7/P8.2A regression: `337 passed`, `12 protected skips`
- contract validation: `183 schemas`, `245 examples`, `214 negative`,
  `9 OpenAPI` passed
- WC test-profile migration dry-run: `1006_wc_approval_foundation` planned
- repository diff hygiene: passed

The generic `nex-wc` Slice Gate currently selects only `test_nex_wc_*` and
`test_wc_*` while measuring the entire package. Cross-service WC tests named
`test_ae_wc_*` are therefore omitted from that scripted run, and pre-existing
modules reduce its package-wide branch result below the gate threshold. The
broader WC regression above explicitly included both naming families. The gate
profile mismatch is retained for reconciliation before the P8-S41 Checkpoint;
it does not lower the focused P8-S33 coverage threshold.

Actual PostgreSQL approval transition smoke remains part of the P8.3 protected
acceptance sequence after the state transition APIs are connected.
