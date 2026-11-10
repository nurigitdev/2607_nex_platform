# MyBee Phase-1 COA-04: Tenant Extension and Legacy Compatibility

## Scope

COA-04 activates approval-backed tenant extension publication for work code
`FL0004011` and proves compatibility with the existing v1 Account source of
record. It adds no second GL Account table and does not rewrite historical
Account codes or UUIDs.

## Implementation

- `FINANCE.COA.EXTENSION_PUBLISH_APPROVED` publishes a tenant-owned DRAFT
  extension under fresh OA `finance:account:manage` authority;
- an extension must derive from a published GLOBAL release with the same chart
  profile;
- every extension entry must be an `800..999` leaf beneath an active GLOBAL
  family with the same category;
- a numeric extension code that already exists in tenant `eos_account` is
  rejected before publication;
- the stable code/semantic identity ledger prevents meaning reassignment across
  tenant extension releases;
- exact business-operation replay returns the committed publication;
- an approved `eos_coa_account_binding` is the explicit compatibility bridge
  between a legacy alphanumeric Account UUID and a unified semantic entry;
- legacy Account code, UUID, voucher FK, and v1 resolve behavior remain
  unchanged.

No new database table or migration was needed. The existing unified release,
entry, identity, adoption, binding, Account, company-policy, PostingRule,
idempotency, and outbox structures remain authoritative.

## PostgreSQL Evidence

The protected smoke connected to `nex_eos_test` as `nex_eos_user`, applied the
full EOS migration inventory in an isolated schema, published the GLOBAL base,
created and published one tenant `...800` extension through the governed
operation, and removed the schema afterward with zero residue.

## Verification

```text
focused COA-03/04 tests: 43 passed, 2 protected skips
actual nex_eos_test COA-04 PostgreSQL smoke: 1 passed
focused coa_operations.py coverage: 99%
focused coa_api.py coverage: 100%
nex-eos Slice Gate: 913 passed, 27 explicit protected skips
Slice Gate statement coverage: 96.18% (threshold 95.00%)
Slice Gate branch coverage: 94.91% (threshold 94.00%)
coa_operations.py branch coverage: 99.06%
coa_api.py branch coverage: 100.00%
contract validation: PASS (233 schemas / 292 examples / 245 negatives / 10 OpenAPI)
Golden Journey transition audit: PASS
product dependency audit: PASS
remote provider requirement: NONE
```
