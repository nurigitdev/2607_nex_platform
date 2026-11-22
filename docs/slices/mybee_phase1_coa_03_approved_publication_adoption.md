# MyBee Phase-1 COA-03: Approved Publication and Company Adoption

## Scope

COA-03 activates the approved unified COA candidate without replacing the
existing tenant GL source of record. Product Accounting publishes an admitted
GLOBAL release, and a tenant company adopts that release by binding its
postable entries to existing tenant `eos_account` rows.

The boundary preserves these decisions:

- a GLOBAL product release has no synthetic tenant owner;
- the publishing actor still has a real OA tenant and subject identity;
- publication requires `finance:catalog:publish` and an exact immutable source
  admission record;
- company adoption requires `finance:account:manage`, an active LegalEntity,
  an effective published release, an active tenant account, an approved
  company account policy, and a published PostingRule;
- tenant extensions must identify the adopted GLOBAL release as their base;
- stable account-code and semantic-key identities cannot be reassigned by a
  later publication;
- publication and adoption use the existing EOS business-operation,
  idempotency, transaction, and outbox coordinator.

COA-03 does not seed an operating chart, create tenant accounts, or change the
legacy account API. Those remain explicit governed operations.

## Implementation

- `FINANCE.COA.PUBLISH_APPROVED` publishes an admitted DRAFT atomically and
  activates the stable code-identity ledger;
- `FINANCE.COA.ADOPT_APPROVED` records a company adoption and its account
  bindings atomically;
- exact replay returns the committed result, while changed adoption semantics,
  binding count, or binding evidence fail closed;
- OA denial is distinct from OA unavailability, and malformed authority
  evidence is unavailable rather than trusted;
- internal service-token-protected HTTP routes expose both operations;
- OpenAPI documents the request, result, idempotency, and problem boundaries;
- runtime configuration remains unavailable until database, OA authorization,
  and pinned publication admissions are all configured.

## PostgreSQL Evidence

The protected smoke connected to `nex_eos_test` as `nex_eos_user`, created an
isolated schema, applied the full NeX-EOS migration inventory through
`2518_eos_unified_coa`, published a four-level GLOBAL release, adopted it for a
real tenant LegalEntity, and verified the account binding. The schema was
dropped afterward, leaving zero smoke residue.

## Verification

```text
focused COA-03 tests: 32 passed, 1 protected skip
actual nex_eos_test PostgreSQL smoke: 1 passed
focused coa_operations.py coverage: 99%
focused coa_api.py coverage: 100%
nex-eos Slice Gate: 902 passed, 26 explicit protected skips
Slice Gate statement coverage: 96.15% (threshold 95.00%)
Slice Gate branch coverage: 94.84% (threshold 94.00%)
unified_coa.py branch coverage: 96.25%
coa_operations.py branch coverage: 98.84%
coa_api.py branch coverage: 100.00%
contract validation: PASS (233 schemas / 292 examples / 245 negatives / 10 OpenAPI)
Golden Journey transition audit: PASS
product dependency audit: PASS
remote provider requirement: NONE
```

The final NeX-EOS Slice Gate report is stored at
`reports/quality/mybee-coa-03-slice.coverage.json`.
