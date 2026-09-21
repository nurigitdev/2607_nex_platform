# Slice 0913: Centralized CX authorization enforcement

## Goal

Remove route-local service authorization and enforce one CX caller policy.

## Implementation

- Eleven CX route modules now use `nex_cx.authorization.authorize_cx_request`.
- The guard validates the `nex-cx` audience and `service:call` scope through the
  Slice 0912 resolver foundation.
- AE API, AG, and internal CX calls are permitted; OA and MO cannot assert CX
  ownership context and receive a consistent 403 problem response.
- Successful requests retain only caller service ID and validated scopes in
  request state. Bearer tokens are not retained.
- The S91 coupling audit now reads its historical duplication evidence from the
  Slice 0906 note while reporting zero remaining local helper definitions.

This slice changes no route shape, table, migration, or persistent record.

## Verification

```text
central authorization evidence: PASS modules=11/11 failed checks=0
focused tests: 36 passed; target statement/branch coverage: 100%
affected route regression: 404 passed, 1 known warning
aggregate regression: 6371 passed, 1 known warning
statement=76440/77321=98.86059414648025%
branch=17726/18376=96.46277753591642%
contract validation: 82 schemas, 133 examples, 97 negative examples, 7 OpenAPI
```
