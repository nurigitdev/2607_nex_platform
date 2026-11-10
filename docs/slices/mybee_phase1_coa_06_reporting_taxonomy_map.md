# COA-06 K-IFRS/DART Reporting Taxonomy Map

## Scope

- Add versioned EOS persistence for approved reporting-taxonomy releases and
  COA-entry mapping rules.
- Add the signed internal reporting-map query at
  `GET /internal/v2/finance/reporting-map`.
- Require fresh OA `finance:report:read` authority and effective published
  release evidence for every query.
- Keep regulated reporting fail-closed while any selected mapping remains
  `MAPPING_PENDING`.

## Decisions

- EOS owns the reporting release, source/proof/content hashes, effective
  period, mapping status, context, and immutable rule identity.
- A mapping is explicitly one of `MAPPING_PENDING`, `RESOLVED`, or
  `NOT_APPLICABLE`. Only `RESOLVED` may carry a taxonomy concept identifier.
- The product registry is intentionally
  `SOURCE_PENDING_NOT_ADMITTED`. No DART/K-IFRS concept identifier is invented
  or admitted without an approved source artifact and Product Accounting
  proof.
- Synthetic concept identifiers are confined to test fixtures. They do not
  enter the product registry or seed data.
- Internal inspection may read pending mappings, but regulated export returns
  `EOS_COA_REPORTING_MAPPING_PENDING` until every selected rule is resolved or
  explicitly not applicable.
- General-ledger account codes and reporting taxonomy concept identifiers are
  separate identities.
- No remote model provider is required for this Slice.

## Persistence

- Migration `2519_eos_coa_reporting_map` adds:
  - `eos_coa_reporting_release`
  - `eos_coa_reporting_map`
- Both table names remain within the established PostgreSQL identifier budget.
- Release publication is exact-evidence and replay safe. Source, approval, or
  content hash drift fails closed.

## Verification

- Focused regression: `18 passed, 1 skipped` without protected PostgreSQL.
- Actual `nex_eos_test` PostgreSQL smoke: `19 passed`:
  - database/user identity `nex_eos_test / nex_eos_user` verified;
  - all migrations, including `2519_eos_coa_reporting_map`, applied in an
    isolated schema;
  - draft creation, exact publication, resolved regulated lookup, and evidence
    projection passed;
  - isolated schema removed after execution.
- EOS Slice Gate: `937 passed, 29 skipped`.
- EOS coverage: statement `96.30%`, branch `94.89%`.
- New reporting repository/service and API coverage: statement `100.00%`,
  branch `100.00%`.
- Contract validation: `233` schemas, `292` examples, `245` negative examples,
  and `10` OpenAPI documents passed.
- Golden-journey transition and demo-product dependency audits passed.

## Follow-up

- Product Accounting must admit an authoritative taxonomy source and immutable
  concept mapping release before regulated reporting can become eligible.
- COA-07 owns release diff, observability, concurrency/replay hardening, and
  upgrade rehearsal across the COA foundation.
