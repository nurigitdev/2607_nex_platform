# P8-S34 Approval create_or_get Semantics

## Decision

WC resolves approval publication by this stable identity:

```text
tenant_id + approval_domain + source_ref
```

For `NSL_WRITE`, `source_ref` is the certified NSL `ApprovalRequestId`.
The unique key introduced in P8-S33 is therefore the database serialization
point; no additional table or migration is required.

## Replay Rules

- New source identity: create one `ApprovalWorkItem`.
- Existing source identity with the same upstream `semantic_hash` and the same
  WC immutable binding projection: return the original item with
  `created=false`.
- Existing source identity with a different hash, target, resume binding,
  provider binding, or expiry: return deterministic `409` and preserve the
  original row.
- A retry may supply a new candidate UUID or creation timestamp; neither can
  replace the original durable identity.

WC does not reconstruct the protected NSL semantic envelope. It compares the
opaque certified hash and the safe bindings it owns. This avoids coupling WC to
NSL internals while still failing closed on visible binding drift.

## Verification

- focused approval persistence/idempotency tests: `35 passed`
- cumulative `nex_wc.approvals` coverage: `100% statement`, `100% branch`
- WC/P7/P8 regression: `348 passed`, `12 protected skips`
- contract validation: `183 schemas`, `245 examples`, `214 negative`,
  `9 OpenAPI` passed
- Ruff and repository diff hygiene: passed
- no schema/migration churn after P8-S33
