# Slice 0912: CX access context contract and resolver

## Goal

Create one immutable, token-free ownership context at the CX service boundary.

## Implementation

- `CxAccessContext` carries the authenticated caller service, canonical OA
  tenant/user ids, request/trace correlation, and validated service scopes.
- The resolver validates the `nex-cx` audience and `service:call` scope, then
  permits only AE API, AG, or an internal CX caller to assert owner context.
- Tenant, subject, request, and trace identifiers are bounded and reject path
  traversal, whitespace, and unsupported characters.
- Canonical ownership references can be built from the context, and ownership
  comparison fails closed for malformed or cross-owner data.
- Bearer tokens and private identity attributes are never retained or emitted.

This slice changes no route, table, migration, or persistent record. Central
route authorization is intentionally isolated in Slice 0913.

## Verification

```text
contract evidence: PASS checks=5/5 postgres_required=False dgx_required=False
focused tests: 23 passed; target statement/branch coverage: 100%
aggregate regression: 6362 passed, 1 known warning
statement=76414/77295=98.8602108803933%
branch=17742/18392=96.46585471944324%
contract validation: 82 schemas, 133 examples, 97 negative examples, 7 OpenAPI
```
