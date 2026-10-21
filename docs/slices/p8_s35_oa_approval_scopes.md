# P8-S35 OA Approval Scopes

## Scope Activation

P8 activates these canonical OA scopes:

```text
approval:read
approval:decide
```

They use the existing OA authorization model. A scope may be granted directly
by a tenant membership or inherited from an active tenant role, including a
role assigned through an active group. Effective authorization remains the
union calculated by `OaEffectiveAuthorizationResolver`.

No approval-specific user database, permission table, token type, or scope
catalog table is introduced.

## Least Privilege

- `approval:read` does not imply `approval:decide`.
- `approval:decide` does not imply `approval:read`.
- Neither scope is added to `DEFAULT_MEMBERSHIP_SCOPES`.
- Inactive membership remains denied before scope evaluation.
- Unknown `approval:*` names are not accepted by the approval-specific guard.

P8-S36 will consume fresh OA effective authorization immediately before a WC
decision commit. This Slice only establishes and verifies the OA scope model;
it does not mutate a WC decision.

## Verification

- focused resolver tests: `9 passed`
- focused resolver coverage: `100% statement`, `100% branch`
- OA identity/trust regression: `1092 passed`, `11 protected skips`
- contract validation: `183 schemas`, `245 examples`, `214 negative`,
  `9 OpenAPI` passed
- direct membership read-only grant and decide denial
- active role grant for read and decide
- inactive membership, unknown scope, and default membership non-escalation
