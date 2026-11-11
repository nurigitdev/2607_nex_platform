# MyBee Phase 1 S1-03 AccountingPeriod and Close/Post Concurrency

## Scope

- Activate the existing `eos_accounting_period` schema as the EOS source of
  truth for company accounting periods.
- Enforce the forward-only `OPEN -> CLOSING -> CLOSED` lifecycle and reject
  normal reopen or mutation of a closed period.
- Provide the shared `FOR UPDATE` posting-admission primitive required by
  `SRS-PER-001` and `SRS-PER-002`.
- Expose signed, OA-authorized `FINANCE.PERIOD.GET` and
  `FINANCE.PERIOD.CLOSE` service routes.
- Preserve migration `2517` unchanged and apply all runtime hardening through
  additive migration `2521_eos_accounting_period_runtime`.

## Runtime Design

`SqlAlchemyEosAccountingPeriodRepository.lock_open_for_post()` accepts the
caller's live SQLAlchemy `Session`. It selects the exact tenant/company period
containing the posting date with `FOR UPDATE` and returns only when the state
is `OPEN`. The lock therefore remains held until the caller's journal-posting
transaction commits or rolls back.

Close uses the same period row lock:

1. `OPEN` at the expected version advances to durable `CLOSING`.
2. A repeated start-close request is an exact state replay.
3. `CLOSING` advances to `CLOSED` only with a SHA-256 close proof and a
   non-empty ledger cutoff watermark.
4. Posting admission in `CLOSING` or `CLOSED` fails with
   `EOS_ACCOUNTING_PERIOD_NOT_OPEN`.
5. `CLOSED` cannot return to `OPEN` or mutate its final evidence through this
   runtime or through direct PostgreSQL writes.

Period creation is repository-owned in this Slice; it is not added to the
canonical public API. The runtime requires an active, effective LegalEntity,
starts every period at version 1, admits exact replay, and rejects company
date-range overlap.

## PostgreSQL Guards

Migration `2521` adds no table. It:

- serializes overlap decisions with a transaction advisory lock keyed by
  tenant and company;
- preserves the existing inclusive date-range invariant under concurrent
  inserts;
- makes period identity, fiscal number, date range, and creation timestamp
  immutable;
- permits only `OPEN -> CLOSING -> CLOSED` with a one-version increment;
- requires final close proof, close timestamp, and ledger watermark for
  `CLOSED`;
- rejects direct reopen and state/evidence tampering with SQLSTATE `23514`.

## Authorization and API

- `GET /internal/v2/finance/periods/{period_id}`
  - operation: `FINANCE.PERIOD.GET`
  - business scope: `finance:period:read`
  - exact tenant and company scope required
- `POST /internal/v2/finance/periods/{period_id}:close`
  - operation: `FINANCE.PERIOD.CLOSE`
  - business scope: `finance:period:close`
  - signed service trust and fresh OA authority required
  - `expected_version` protects the state transition

Malformed OA evidence is unavailable (`503`), while inactive subjects,
tenant/subject mismatch, and missing business scopes are denied (`403`).

## Acceptance Evidence

- Focused SQLite/runtime/API suite: `8 passed, 1 protected smoke skipped`.
- New runtime and API coverage: statement `100.00%`, branch `100.00%`.
- Actual `nex_eos_test` protected PostgreSQL smoke: `9 passed`.
  - database/user identity verified as `nex_eos_test / nex_eos_user`;
  - migrations through `2521_eos_accounting_period_runtime` applied in an
    isolated schema;
  - a posting transaction held the period row while close waited;
  - after the posting commit, close entered `CLOSING`;
  - all 20 later posting attempts were rejected;
  - concurrent overlapping inserts produced exactly one commit and one
    SQLSTATE `23505` conflict;
  - isolated schema cleanup left zero residue.
- S1-01/S1-02/COA-02..07 affected regression: `192 passed, 8 skipped`.
- EOS Slice Gate: `951 passed, 31 skipped`.
- EOS Slice Gate coverage: statement `96.54%`, branch `95.24%`.
- Contract validation: `233` schemas, `292` examples, `245` negative examples,
  and `10` OpenAPI documents passed.
- Golden Journey transition and demo/product dependency audits passed.

## Deferred Boundary

S1-03 establishes period state, authorization, locking, and evidence shape.
S5 retains ownership of the full financial-close gate, including outstanding
financial-operation checks, FX close-rate release, monetary remeasurement,
and the governed human close workflow. S1-03 does not claim those checks are
complete.
