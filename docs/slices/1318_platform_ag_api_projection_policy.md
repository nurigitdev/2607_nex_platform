# Slice 1318: Platform AG API projection policy

## Outcome

- Added a profile-aware AG projection policy shared by the platform runtime
  and AG startup path.
- Managed `local_mock` processes require `memory`; managed protected profiles
  require `api` and reject the legacy `postgres` mode before database engines
  can be created.
- Added `api` as an explicit AG source mode. Its unbound projections return no
  store instead of silently substituting memory or opening another service's
  database.
- Retained the four direct PostgreSQL readers only for historical smoke and
  regression callers that do not opt into a managed `NEX_PROFILE`.

## Decision

The compatibility adapters are quarantined, not presented as the target
runtime. This lets existing evidence remain reproducible while every process
started by the S132 manifest follows the service-API-only invariant. Missing
API projection clients remain visibly unavailable; implementing the complete
cross-service operator timeline and deleting the adapters belongs to S138.

## Verification

- Focused regression: `294 passed`.
- Slice Gate (`nex-ag`): `2,486 passed`; statement `98.89%`, branch
  `96.52%`.
- Changed policy and evidence scopes: statement `100.00%`, branch `100.00%`.
- Evidence verifies protected rejection, unmanaged compatibility, absence of
  DB registry construction, absence of memory fallback, and the four-file
  quarantine inventory.
- Contract validation: `156` schemas, `214` examples, `184` negative
  examples, and `7` OpenAPI documents.
- No PostgreSQL database or remote provider is contacted.
