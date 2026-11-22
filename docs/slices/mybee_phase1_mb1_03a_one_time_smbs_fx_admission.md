# MyBee Phase-1 MB1-03A: One-Time SMBS FX Admission and History

## Scope

MB1-03A validates the existing S1-04 FX persistence design with the public
Seoul Money Brokerage Services TodayExRate page. It adds a bounded operator
adapter for one USD/KRW publication and a read API for immutable daily history.
It does not add a scheduler, background downloader, legal claim, correction
workflow, or new database table.

The canonical page is:

`http://www.smbs.co.kr/ExRate/TodayExRate.jsp`

The site is HTTP-only. TLS verification must not be disabled or misrepresented
as successful. URL capture therefore requires an explicit
`--allow-insecure-http`, writes the exact raw response before parsing, and
records `transport_security=HTTP_UNVERIFIED`. The preferred path is an
operator-retained source file.

## One-Time Adapter

`scripts/operations/import_smbs_fx_once.py` performs these bounded steps:

1. admit either one local source file or one explicitly allowed HTTP capture;
2. decode the declared EUC-KR or UTF-8 document without replacement;
3. remove HTML comments and locate the visible market-base-rate table;
4. decode the page's `d1` through `d5` text tokens;
5. require exactly one positive USD/KRW rate and one displayed rate date;
6. hash the exact raw source and retain parser/acquisition provenance;
7. create a deterministic RateSnapshot ID and canonical
   `FINANCE.FX_RATE.IMPORT` request;
8. default to dry-run; call EOS only when `--commit` is explicit.

The operator supplies `published_at` with a timezone. The adapter does not
invent a publication timestamp from the page date. Exact replay is idempotent;
different content at the same provider/date/publication identity conflicts and
does not overwrite history.

Example file-mode dry-run:

```bash
./.venv/bin/python scripts/operations/import_smbs_fx_once.py \
  --input-file /protected/evidence/smbs-20261111.html \
  --published-at 2026-11-11T09:05:00+09:00 \
  --tenant-id <tenant> \
  --subject-id <finance-publisher> \
  --company-id <legal-entity-uuid> \
  --policy-id <approved-fx-policy-uuid>
```

Commit mode additionally requires `--commit`, `--eos-base-url`, and a signed
service token in `NEX_EOS_FX_IMPORT_SERVICE_TOKEN` unless another environment
variable name is selected. The token is never written into the report.

## Persistence and History

No migration was added. Existing migration
`2522_eos_fx_rate_policy_snapshot` already provides:

- versioned approved company FX policies;
- immutable daily `eos_fx_rate_snapshot` rows;
- source URI, source row identity, raw SHA-256, rate and publication dates,
  quote unit, normalized rate, calendar, timezone, and provenance;
- source-identity and canonical-snapshot idempotency guards;
- database triggers rejecting UPDATE and DELETE.

`GET /internal/v2/finance/fx-rate-snapshots` now exposes
`FINANCE.FX_RATE.HISTORY`. It requires signed service trust and fresh
`finance:fx:read` authority, scopes by tenant/company/purpose/currency pair and
inclusive date range, orders newest publication first, and limits one request
to 500 rows.

At Slice entry, `nex_eos_dev` and `nex_eos_test` public schemas had not applied
the EOS migration chain; the prior S1-04 smoke used an isolated schema and
removed it after verification. MB1-03A continues to use protected isolated
PostgreSQL smoke rather than silently migrating or seeding an authoritative
business database without a real tenant, LegalEntity, approved policy, OA
authority, and service token.

## Deferred Boundaries

- scheduled daily acquisition and retry/backoff;
- an approved Korean holiday-calendar provider;
- paid data-reception or other source-use agreement;
- correction/retraction and superseding-publication workflow;
- multi-currency parsing and atomic multi-row batch admission;
- raw evidence migration to private object storage.

These items remain backlog work. The one-time adapter is not an automatic FX
feed.

## Verification

```text
live SMBS HTTP opt-in dry-run: PASS
displayed rate date: 2026-11-11
parsed USD/KRW rate: 1343.30
transport evidence: HTTP_UNVERIFIED
focused MB1-03/03A and EOS FX tests: 99 passed, 1 protected skip
MyBee Phase-1 regression: 170 passed
MyBee/EOS affected regression: 241 passed, 10 protected skips
actual nex_eos_test isolated-schema PostgreSQL smoke: 42 passed
EOS Slice Gate: 1162 passed, 32 explicit protected skips
Slice Gate statement coverage: 96.84%
Slice Gate branch coverage: 95.69%
MyBee package statement coverage: 99.88%
MyBee package branch coverage: 99.22%
contract validation: PASS
MyBee platform lock: PASS
database migrations added: NONE
remote model provider requirement: NONE
```

The protected PostgreSQL smoke verified database/user identity, applied the
complete EOS migration chain through `2522` in an isolated schema, exercised
policy and snapshot admission, history query, concurrency and immutable
mutation guards, then dropped the schema and confirmed zero residue.

## MB1-03B Amendment

MB1-03B later split the physical persistence model. Provider publication data
now lives once in tenant-neutral `eos_fx_market_rate`; the existing
`eos_fx_rate_snapshot` became an immutable tenant/company/policy adoption that
references the shared observation. The MB1-03A request and operator CLI remain
compatible and the EOS repository performs both steps atomically.
