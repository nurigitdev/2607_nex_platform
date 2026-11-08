# P8-S14: Account Minimum Model

Completed on 2026-10-21. NeX-EOS now owns tenant-scoped canonical Account
identities for Golden A voucher construction.

## Scope

- Added migration `2505_eos_account` and table `eos_account`.
- Added immutable `account_id`, tenant-unique display code, name, category,
  account type, status, effective period, and version.
- Added stable lookup and business-date effective lookup.
- Limited initial categories to asset, liability, equity, revenue, and expense.
- Wired the Account repository into the EOS dependency container only when the
  EOS database runtime is configured.

The effective interval is half-open: `effective_from <= date <
effective_until`. Inactive, expired, unknown, and cross-tenant Account refs do
not resolve through the effective lookup.

## Verification

- Focused Account regression: 18 passed.
- Actual dev/test PostgreSQL migrations applied `2505`.
- Protected PostgreSQL smoke connected as `nex_eos_user@nex_eos_test`, verified
  migration identity, effective Account resolution, tenant isolation, and zero
  residue.
- EOS Slice Gate: 146 passed, 7 protected skips.
- EOS statement coverage: 99.59%; branch coverage: 100%.
- Contract validation: 174 schemas, 236 examples, 204 negative examples, and
  9 OpenAPI documents.
- Remote model providers were not required.
