# P9-S15: EOS Project and Historical Membership Verification

## Scope

P9-S15 keeps NeX-EOS as the Project and Project-membership authority. NeX-WA
uses signed, bounded verification APIs and never reads EOS tables directly.

```text
POST /internal/v1/projects:verify-batch
POST /internal/v1/project-memberships:verify-at
caller = nex-wa
audience = nex-eos
scopes = service:call + project:verify
operation ids = PROJECT.PROJECT.VERIFY_BATCH / PROJECT.MEMBERSHIP.VERIFY_AT
```

Project verification distinguishes `VERIFIED`, `PROJECT_NOT_FOUND`,
`PROJECT_INACTIVE`, and `TENANT_MISMATCH`. Historical membership evaluates the
stored interval as `[valid_from, valid_to)`, so a member removed after an event
remains valid for that event while a member joining afterward does not.

## Persistence

No migration is introduced. The routes reuse `eos_project` and
`eos_project_member`. Repository additions are read-only tenant-safe queries.
The current membership table stores one lifecycle interval per
tenant/Project/subject relationship; multi-interval reactivation history remains
outside this Slice and must not be inferred.

## Verification

Tests cover current and historical membership, removed-after-event,
joined-after-event, inactive and cross-tenant Projects, missing membership,
batch limits, malformed projections, dependency outage, caller/scope admission,
SQLite repository behavior, machine-readable contracts, and installed routes.

- EOS regression: `719 passed, 22 skipped`
- EOS aggregate coverage: statement `95.05%`, branch `93.51%`
- New verification boundary: statement `100%`, branch `100%`
- Contract validation: `223` schemas, `287` positive examples, `241` negative
  examples, and `10` OpenAPI documents
- Ruff and repository diff hygiene: passed

The existing EOS profile excluding this Slice was approximately `93.22%`
branch-covered. P9-S15 raises the aggregate to `93.51%`; it does not claim the
historical `94%` aggregate threshold. The new boundary is held at `100%/100%`,
and the remaining debt is concentrated in pre-existing installed transport and
demo-runtime modules.
