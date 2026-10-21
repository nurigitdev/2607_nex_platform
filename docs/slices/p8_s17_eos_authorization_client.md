# P8-S17 EOS Authorization Client

## Outcome

NeX-EOS now has a fail-closed client boundary for fresh
`finance:voucher-draft:create` authorization. It verifies the admitted service
caller, exact `nex-eos` audience, `service:call`, on-behalf-of tenant/subject,
active OA membership, business scope, revision hash, and command target.

OA v2.1 currently grants business scopes at tenant level. Optional
`project_ids`, `org_unit_ids`, and `resource_refs` constraints are enforced when
an authorization source supplies them. Their absence means tenant-wide scope;
it does not bypass EOS Project/Account/resource validity checks performed at
the authoritative command boundary.

Typed OA inactive/not-found outcomes map to non-retryable 403 denial. Transport,
timeout, and malformed dependency failures fail closed without leaking endpoint
details or mutating EOS state.

## Verification

- focused regression: 26 passed; `authorization.py` statement/branch coverage
  100%/100%
- EOS Slice Gate: 237 passed; statement coverage 99%, branch coverage 100%
- tests cover service trust, principal/scope/revision validation, optional
  target constraints, typed denial, dependency failure, and HTTP shape
- no database migration or remote provider is required
