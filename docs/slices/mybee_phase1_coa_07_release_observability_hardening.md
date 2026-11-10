# COA-07 Release, Observability, and Hardening Closure

## Scope

- Add deterministic COA release diff preview and metadata-only operations
  snapshot APIs.
- Harden tenant/company adoption overlap decisions against concurrent
  PostgreSQL transactions.
- Re-run the complete COA-02..07 PostgreSQL protected matrix, account-policy
  overlap smoke, candidate admission regression, and EOS Slice Gate.
- Close the COA packet without adding new business-state tables or requiring a
  remote model provider.

## Runtime Boundaries

- `GET /internal/v2/finance/coa/releases/diff`
  - compares two releases only when scope, owner, and chart profile agree;
  - reports added, removed, changed, and unchanged account codes;
  - compares parent account codes rather than release-local parent UUIDs;
  - emits a deterministic evidence hash over source content hashes and diff.
- `GET /internal/v2/finance/coa/operations`
  - exposes aggregate release, entry, adoption, and reporting-mapping counts;
  - exposes no company payload or account detail;
  - reports regulated-reporting readiness as blocked when pending mappings
    remain.
- Both routes require signed service trust and fresh OA
  `finance:catalog:publish` authority.

## Concurrency Correction

The original `2518` adoption trigger used an `EXISTS` overlap check without a
serialization boundary. Two concurrent transactions could both observe no
committed adoption and admit overlapping intervals.

Migration `2520_eos_coa_adoption_concurrency` now acquires a transaction-level
advisory lock keyed by tenant and company before evaluating release and period
constraints. A hash collision may only serialize unrelated companies; it
cannot weaken the overlap invariant. No table was added and the existing
`eos_coa_company_adoption` SoR remains unchanged.

Actual concurrent PostgreSQL execution produced exactly one `COMMITTED`
outcome and one SQLSTATE `23505` overlap rejection.

## Acceptance Mapping

- `PG-CA01-08`: product/tenant publisher scopes and forged authority fail
  closed in existing COA route and authorization regressions.
- `PG-CA01-09`: wrong-scope and invalid parent references are rejected by
  protected PostgreSQL triggers with no partial mutation.
- `PG-CA01-10`: exact publication replay remains idempotent; published entry
  update is rejected as immutable in actual PostgreSQL.
- `PG-CA01-11`: tenant/company adoption overlap is serialized by `2520`; the
  concurrent smoke proves one winner and one deterministic conflict.
- `PG-CA01-12`: existing BusinessOperation replay tests remain green; an
  injected post-insert crash rolls the transaction back to zero rows.
- `PG-CA01-13`: COA-01/01A candidate and Product Accounting admission tests
  remain fail-closed and pass.
- `PG-CA01-14`: the existing account/voucher and Golden Journey regressions
  remain green in the EOS Slice Gate.
- `PG-CA01-15`: non-postable, missing adoption, currency, and ambiguity cases
  remain fail-closed in the semantic resolver matrix.
- `PG-CA01-16`: every protected smoke uses an isolated schema; the final
  `mybee_coa%` schema count is `0`.

## Verification

- COA-01/01A source and approval admission regression: `72 passed`.
- Actual `nex_eos_test` PostgreSQL matrix:
  - identity `nex_eos_test / nex_eos_user` verified;
  - S1-02 and COA-02..07 protected tests: `164 passed`;
  - migrations through `2520_eos_coa_adoption_concurrency` applied;
  - upgrade diff, published immutability, concurrent overlap, rollback, and
    cleanup passed;
  - remaining isolated schemas: `0`.
- EOS Slice Gate: `943 passed, 30 skipped`.
- EOS coverage: statement `96.40%`, branch `94.99%`.
- New release-admin module and API: statement `100.00%`, branch `100.00%`.
- Contract validation: `233` schemas, `292` examples, `245` negative examples,
  and `10` OpenAPI documents passed.
- Golden-journey transition and demo-product dependency audits passed.

## Historical Test Hygiene

The COA-01 test previously asserted that the repository's highest migration
must remain `2517`. That assertion was valid only at the COA-01 design-only
checkpoint and became stale once COA-02 began. It now verifies the historical
contract directly: the COA-01 closure declares no migration and no migration
is named as a COA-01 artifact. Later additive migrations are no longer blocked.

## Follow-up

- Authoritative K-IFRS/DART source admission remains an accounting-owner task;
  regulated reporting stays fail-closed until that release is approved.
- Future admin UI may consume these two internal read APIs, but COA-07 does not
  widen the current MyBee Phase-1 user interface.
