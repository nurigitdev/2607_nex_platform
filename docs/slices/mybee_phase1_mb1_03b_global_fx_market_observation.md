# MyBee Phase-1 MB1-03B: Global FX Market Observation and Tenant Adoption

## Decision

An external provider publication is tenant-neutral market reference data.
Whether and how it may be used for transaction, close, settlement, or tax
accounting remains a tenant and LegalEntity decision. MB1-03B therefore splits
one former mixed record into two immutable layers:

1. `eos_fx_market_rate`: one global provider observation;
2. `eos_fx_rate_snapshot`: one tenant/company/policy adoption of that
   observation.

`eos_fx_rate_policy` remains tenant/company scoped and unchanged.

## Persistence Boundary

Migration `2523_eos_fx_market_rate_adoption`:

- creates tenant-neutral `eos_fx_market_rate`;
- globally deduplicates provider, source record, publication issue, currency
  pair, and rate date;
- fails closed when legacy tenant rows contain different core content for the
  same global source identity;
- backfills a market observation for every legacy snapshot source;
- adds `market_rate_id` to tenant snapshots;
- replaces the incorrect tenant-only source unique key with a
  tenant/company/policy/market adoption key;
- removes duplicated source payload columns from the tenant snapshot;
- preserves existing snapshot hashes for migrated rows and uses the V2 hash
  domain for new adoptions;
- keeps policy, market observation, and adoption immutable.

The database admission trigger joins policy, market observation, and adoption
and rejects provider/pair, effective interval, publication selector,
normalized rate, or effective-date disagreement.

## Runtime Compatibility

`FINANCE.FX_RATE.IMPORT` keeps the MB1-03A request shape. The EOS repository
atomically:

1. validates the tenant company policy;
2. serializes the global source identity on PostgreSQL;
3. admits or reuses one market observation;
4. creates the tenant/company/policy adoption;
5. returns the previous response projection plus `market_rate_id` and
   `market_rate_hash` lineage.

Resolve and history remain tenant scoped and join the shared market source only
after matching the caller's approved tenant/company policy. A global market
row alone grants no accounting authority.

## Concurrency and Isolation

- PostgreSQL advisory locking serializes the global source identity.
- Concurrent imports from different tenants reuse one market observation.
- The same tenant may adopt the same observation for multiple LegalEntities.
- Different source content at an existing global identity fails closed.
- Exact tenant adoption replay returns the existing immutable snapshot.

## Deferred Scope

- a separately authorized platform-wide source-admission API;
- automatic scheduled SMBS acquisition;
- correction, retraction, and supersession of provider publications;
- private object-storage retention for raw source bytes;
- multi-currency atomic source batches.

The current combined import boundary is retained for compatibility and still
requires signed service trust plus fresh `finance:fx:publish` authority.

## Verification

- Focused FX regression: `103 passed, 2 skipped`.
- MyBee package regression: `170 passed`.
- EOS MyBee regression: `245 passed, 11 skipped`.
- Actual `nex_eos_test` protected smoke: `47 passed`; this includes the
  `2522 -> 2523` legacy upgrade, cross-tenant and cross-company concurrent
  adoption, global observation reuse, immutable-row guards, and zero residue.
- Slice Gate: `PASS`, `72` selected tests, statement coverage `96.89%`, and
  branch coverage `95.95%`.
- Remote model providers are outside this persistence boundary and were not
  required.
