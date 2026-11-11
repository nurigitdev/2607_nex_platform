# MyBee Phase 1 S1-04 Approved FX Policy and RateSnapshot Lineage

## Scope

- Add company-scoped, versioned, approved FX policy persistence.
- Add immutable FX `RateSnapshot` persistence with source record, publication,
  calendar, timezone, URI, raw-source hash, and canonical snapshot hash.
- Expose signed, fresh-OA-authorized `FINANCE.FX_RATE.IMPORT` and
  `FINANCE.FX_RATE.RESOLVE` boundaries.
- Normalize vendor quote units with `Decimal`; a published JPY rate quoted per
  100 units is divided by `100` before it can be returned to accounting.
- Fail closed for missing policy, unavailable source data, stale data, wrong
  provider/pair, or a FIRST/FINAL publication mismatch.
- Preserve the K-IFRS and tax policy tracks as distinct policy purposes. A
  `TAX_VALUATION` policy cannot silently satisfy `TRANSACTION_SPOT` or
  `MONETARY_CLOSE` resolution.

The canonical plan proposed migration number `2518`, but that immutable number
is already occupied by the unified COA migration in the source-backed
repository. S1-04 therefore uses additive migration
`2522_eos_fx_rate_policy_snapshot`; no migration history was rewritten.

## Persistence Contract

### `eos_fx_rate_policy`

An admitted row is already `APPROVED` and immutable. Its identity and hash bind:

- tenant, LegalEntity, policy ID/version, and effective interval;
- purpose, currency pair, rate kind, provider, and publication selector;
- explicit previous-business-day and maximum-staleness decisions;
- decimal scale and the Phase-1 admitted `HALF_EVEN` rounding mode;
- accounting owner and approval proof.

PostgreSQL serializes one tenant/company/purpose/pair interval with an advisory
transaction lock and rejects overlapping approved policies. Runtime resolution
also requires exactly one effective policy, so corruption or policy ambiguity
cannot silently choose a winner.

### `eos_fx_rate_snapshot`

The snapshot stores the published rate and quote unit separately from the
normalized per-one-unit rate. It also retains the desired date and selected
business date, source record and publication issue, FIRST/FINAL indicator,
source timestamps, calendar, timezone, URI, raw response hash, structured
provenance, and canonical snapshot hash.

Both policy and snapshot tables reject direct PostgreSQL `UPDATE` and `DELETE`.
Correction or retraction therefore requires a later controlled supersession
contract; it cannot rewrite evidence already referenced by an accounting
candidate.

Source import is idempotent on the source provider/record/publication/pair/date
identity. Exact replay returns the admitted snapshot, including when the caller
proposes a new local snapshot UUID. Different content at the same source
identity is a conflict and never overwrites the approved row.

## API and Authorization

- `POST /internal/v2/finance/fx-rate-policies/approved`
  - operation: `FINANCE.FX_POLICY.CREATE_APPROVED`
  - business scope: `finance:fx:publish`
  - controlled accounting-administration boundary for an already approved
    policy and proof
- `POST /internal/v2/finance/fx-rate-batches`
  - operation: `FINANCE.FX_RATE.IMPORT`
  - business scope: `finance:fx:publish`
  - accepts normalized, source-backed batches; does not fetch the Internet
- `GET /internal/v2/finance/fx-rates:resolve`
  - operation: `FINANCE.FX_RATE.RESOLVE`
  - business scope: `finance:fx:read`
  - resolves by company, purpose, pair, desired date, and optional as-of time

All routes also require signed `service:call` trust for the `nex-eos` audience.
Inactive subjects and missing scopes are denied; malformed or unavailable OA
authority returns retryable unavailable rather than bypassing authorization.

## Business-Day Boundary

The Phase-1 resolver supports an explicit, bounded previous-business-day
fallback. It counts Monday through Friday and preserves the source
`calendar_ref` on the snapshot. Statutory-holiday knowledge is not fabricated:
the import adapter must select and attest the effective business date according
to its approved calendar. A future calendar service may replace the weekday
distance helper without changing the snapshot or policy identity.

## SMBS Source Backlog

The intended source currently identified by the product owner is:

`http://www.smbs.co.kr/ExRate/TodayExRate.jsp`

S1-04 deliberately does not scrape or call that page from accounting runtime.
The current production-shaped path is a manually reviewed batch passed through
`FINANCE.FX_RATE.IMPORT`, with the source URI, row identity, publication issue,
timestamps, quote unit, raw-response SHA-256, and acquisition mode retained in
the snapshot.

A later source-adapter Slice should add `SmbsFxSourceAdapter` behind the same
import contract and close these items before automatic refresh is admitted:

1. confirm permitted access, operational terms, and a stable machine-readable
   API or approved HTML acquisition contract;
2. freeze currency-code, quote-unit, publication-issue, FIRST/FINAL, timezone,
   and source-record mapping with parser fixtures;
3. archive or otherwise attest the exact raw response before parsing;
4. add scheduler cadence, rate limiting, timeout/retry, duplicate publication,
   correction/retraction, and provider-outage behavior;
5. integrate an approved Korean business/holiday calendar and record its
   revision;
6. run shadow comparison against manually approved imports before cutover;
7. keep manual import as a controlled recovery path and never fall back to an
   LLM-generated or ad hoc online rate.

Until that backlog is closed, automatic source refresh is not claimed.

MB1-03A later added an explicitly invoked one-time operator adapter and history
read API. Scheduled refresh remains deferred; because the source is HTTP-only,
direct capture is recorded as `HTTP_UNVERIFIED` and the raw response must be
retained.

## Acceptance Evidence

- Focused SQLite/runtime/API suite: `40 passed, 1 protected smoke skipped`.
- New FX runtime/API coverage: statement and branch combined `96%`; API `100%`.
- Actual `nex_eos_test` protected PostgreSQL smoke: `41 passed`.
  - database/user identity verified as `nex_eos_test / nex_eos_user`;
  - migration through `2522_eos_fx_rate_policy_snapshot` applied in an isolated
    schema;
  - concurrent overlapping policy submissions produced one commit and one
    conflict;
  - direct snapshot update and policy delete were rejected by immutable
    triggers;
  - quote-unit normalization, source lineage, and exact resolution passed;
  - isolated schema cleanup left zero residue.
- S1-01 through S1-04 and COA affected regression: `240 passed, 10 skipped`.
- Migration inventory/regression checks: `30 passed`.
- EOS Slice Gate: `991 passed, 32 skipped`; all `6/6` commands passed.
- EOS Slice Gate coverage: statement `96.53%`, branch `95.25%`.
  - `fx_rates.py`: statement `96.00%`, branch `95.08%`.
  - `fx_api.py`: statement and branch `100.00%`.
- Contract validation: `233` schemas, `292` examples, `245` negative
  examples, and `10` OpenAPI documents passed.
- Golden Journey transition and demo/product dependency audits passed.
