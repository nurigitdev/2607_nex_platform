# MyBee Phase-1 S1-02: K-IFRS Account Catalog and PostingRule

## Scope

S1-02 adds the approved account-catalog, company account-policy, and
PostingRule boundaries to EOS while preserving the existing `eos_account`
identity and resolver. The Slice closes the implementation foundation for
`SRS-ACC-001`, `SRS-ACC-002`, `SRS-ACC-003`, `SRS-ACC-005`, and
`SRS-ACC-006` under gates `G-COA` and `PG-ACCOUNT`.

K-IFRS does not prescribe one universal numerical chart of accounts. The
actual MyBee-adopted source file, version, approval, and digest have not yet
been supplied. Consequently, the approved seed manifest is deliberately
`SOURCE_PENDING_NOT_ADMITTED`, contains no invented account codes, and cannot
be used as a runtime seed.

## Persistence Decisions

- `eos_account_catalog_release` records the approved source reference,
  version, SHA-256 digest, effective date, publisher, and approval proof.
- `eos_posting_rule_release` binds one company and catalog release to an
  immutable rule/version/hash and deterministic account-mapping hash.
- `eos_company_account_policy` overlays the stable `eos_account` identity with
  company, hierarchy, postable-leaf, monetary, statement-line, currency, rule,
  and half-open effective-period policy.
- Existing `(tenant_id, account_id)` and `(tenant_id, account_code)` identities
  and the v1 account resolver are unchanged.
- Parent accounts must be approved non-postable accounts in the same tenant,
  company, and catalog release. A postable parent cannot accept children.
- The LegalEntity functional currency must be present in the policy currency
  set. Category and mapping data are approved inputs, never LLM output.
- Policy revision is exact-replay idempotent. Overlapping approved policy
  periods are rejected by repository checks and a PostgreSQL trigger.
- PostgreSQL writes use a tenant/company advisory transaction lock. Foreign
  keys remain tenant-qualified.
- Migration `2517_eos_account_catalog_accounting_period.sql` also reserves the
  dormant AccountingPeriod schema because S1-02 and S1-03 share the frozen
  migration number. S1-03 owns period runtime and API activation.

## API And Trust Boundary

| Operation | Route | Fresh OA scope |
| --- | --- | --- |
| `FINANCE.ACCOUNT.CATALOG_GET` | `GET /internal/v2/finance/account-catalog` | `finance:account:read` |
| `FINANCE.ACCOUNT.CREATE_APPROVED` | `POST /internal/v2/finance/accounts/approved` | `finance:account:manage` |

Both routes first require an admitted `service:call` token for `nex-eos`, then
fresh OA authority for the same tenant and requester. Inactive, cross-tenant,
malformed, missing-scope, or unavailable authorization fails closed.

`FINANCE.ACCOUNT.CREATE_APPROVED` is a governed import/binding boundary for an
externally approved catalog release and proof. It does not invent a K-IFRS
code, publish an unverified seed, or expose a mutable generic Account endpoint.
The canonical NSL boundary remains `READ: FINANCE.ACCOUNT.CATALOG_GET`; a
governed CREATE Skill is admitted only after the corresponding approved source
and workflow artifact exist.

## Verification

Final Slice evidence:

```text
focused regression: 53 passed, 1 protected PostgreSQL test deselected
focused module coverage: 97% account_catalog.py, 100% account_policy_api.py
existing Account/LegalEntity/OpenAPI regression: 141 passed, 2 protected tests deselected
actual PostgreSQL protected smoke: 54 passed
actual database identity: nex_eos_test / nex_eos_user
public-schema migration: 2517_eos_account_catalog_accounting_period applied
public-schema tables: catalog release, company policy, PostingRule, AccountingPeriod
public-schema post-migration row counts: 0 / 0 / 0 / 0
protected temporary-schema migration/FK/overlap-trigger/zero-residue: PASS
EOS Slice Gate: 839 passed, 24 explicit protected skips
EOS statement coverage: 95.82% (threshold 95.00%)
EOS branch coverage: 94.46% (threshold 94.00%)
contract validation: PASS (233 schemas / 292 examples / 245 negative examples / 10 OpenAPI)
Golden transition audit: PASS
product dependency audit: PASS
remote provider requirement: NONE
```

The Slice Gate skips are existing opt-in topology, trust, migration, and
cross-service smokes. The S1-02 PostgreSQL test was separately enabled and
executed against the actual EOS test database; it was not reported as skipped.
