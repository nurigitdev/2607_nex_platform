# Slice 1426: Platform Production Secret Materialization

## Outcome

- Added a provider-neutral secret resolver contract behind the Slice 1425
  pre-start admission gate.
- Materialized exactly sixteen references into five isolated service process
  environments: OA 2, AE 3, CX 2, MO 4, and AG 5.
- Rejected resolver failures, wrong owner/target/generation/version/provider
  metadata, empty or placeholder values, and control characters.
- Kept raw values and opaque references out of projections, smoke evidence,
  exception details, and object representations.

## Decision

The deployment adapter may pass only `environment_for(service_owner)` to that
service process. It must never combine all five mappings. The deterministic
resolver is test-only; an approved external provider adapter and its protected
acceptance remain required by Slice 1431.

## Verification

The Slice smoke uses an in-process deterministic resolver and requires no
network, database, registry, secret-provider, TLS-endpoint, or production
contact. Production deployment remains unapproved.

Focused materialization tests passed `19` cases with statement and branch
coverage both `100%` for the runtime module and smoke runner. The Platform
Slice Gate passed `333` tests with `6` protected PostgreSQL skips, runner
statement/branch coverage `100%`, and contract counts `166/228/196/7`.

The Gate also exposed a date-dependent S140 fixture after its evidence crossed
the 24-hour freshness boundary. The protected-matrix and closure runners now
accept an optional evaluation timestamp for deterministic tests while keeping
the real current time as the production default.
