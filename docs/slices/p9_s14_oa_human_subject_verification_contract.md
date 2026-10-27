# P9-S14: OA Human Subject Verification Contract

## Scope

P9-S14 keeps NeX-OA as the only Human identity and tenant-membership authority.
NeX-WA receives a bounded verification projection and does not create an
identity registry or read OA database tables directly.

```text
POST /internal/v1/identity/subjects:verify-batch
caller = nex-wa
audience = nex-oa
scopes = service:call + identity:subject:verify
batch size = 1..50
```

Each requested subject resolves independently to `VERIFIED`,
`SUBJECT_NOT_FOUND`, `SUBJECT_INACTIVE`, or `TENANT_MEMBERSHIP_MISSING`.
Successful results include only subject and membership revision numbers as
bounded authority evidence. Names, credentials, roles, scopes, metadata, and
raw registry snapshots are not returned.

## Persistence

No migration is introduced. The boundary reuses `oa_subjects` and
`oa_tenant_memberships` through their existing registries.

## Verification

The Slice Gate covers all result states, deterministic evidence hashing,
batch limits `1/50/51`, malformed authority projections, dependency failures,
dedicated scope enforcement, caller rejection, contract validation, and the
installed OA route.

- OA regression: `1,134 passed, 11 skipped`
- OA aggregate coverage: statement `98.41%`, branch `97.52%`
- New verification boundary: statement `100%`, branch `100%`
- Contract validation: `219` schemas, `283` positive examples, `237` negative
  examples, and `10` OpenAPI documents
- Ruff and repository diff hygiene: passed

The two new OA schemas each include a negative privacy fixture. The OA drift
inventory was reconciled from `28` to the actual `30` schemas without relaxing
its positive/negative fixture coverage requirement.
