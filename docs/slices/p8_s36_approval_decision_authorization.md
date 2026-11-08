# P8-S36 Approval Decision Authorization

## Decision-Time Boundary

Every APPROVE or REJECT attempt must call OA effective authorization at decision
time. Inbox-read or planning-time evidence cannot be reused. WC requires:

```text
active principal
approval:decide
exact tenant and subject identity
compatible approval target
metadata-safe OA revision evidence
```

No decision repository is called in this Slice. Therefore every denial,
malformed response, and dependency failure has zero decision mutation by
construction. P8-S37 connects the returned evidence to the immutable commit.

## Target Compatibility

- When `target_approver_ref` is present, exact principal equality authorizes the
  target. Organization and project fields remain the resolved task context.
- Without an exact principal, every configured role, organization, and project
  target must appear in the corresponding OA effective authorization set.
- A task with no target fails closed.

This preserves current principal-targeted approvals while allowing future
role-scoped resolution without weakening the boundary.

## Evidence

The authorizer returns no raw token. It retains only:

- `decided_by`
- `oa_decision_ref`
- `authorization_revision_hash` as a `sha256:` reference
- `authorization_checked_at`
- `authorized_by_oa=true`

An explicit OA decision reference is preserved. Until OA issues one, WC derives
a stable metadata-safe reference from the effective authorization revision.

## Verification

- focused cumulative approval tests: `47 passed`
- cumulative `nex_wc.approvals` coverage: `100% statement`, `100% branch`
- WC/P7/P8 regression: `360 passed`, `12 protected skips`
- contract validation: `183 schemas`, `245 examples`, `214 negative`,
  `9 OpenAPI` passed
- repeated calls prove fresh OA lookup
- exact principal and role/org/project target success
- typed subject denial is `403`; dependency failure is retryable `503`
