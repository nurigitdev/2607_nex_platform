# Slice 1477: S148 Alert Persistence Checkpoint

## Outcome

- Added concise `ag_alerts`, `ag_notify_outbox`, and `ag_notify_attempts`
  PostgreSQL tables with operations, claim, and history indexes.
- Added optimistic alert revision updates and transactional alert/outbox
  creation with unique delivery idempotency.
- Added bounded notification leases, expired-lease recovery, retry scheduling,
  terminal delivery states, and append-only attempt receipts.
- Added SQLite restart regression proving recovery and zero residue without
  treating SQLite as PostgreSQL compatibility evidence.

Slice 1478 adds deterministic local and mock external transport execution on
top of the durable outbox.

## Verification

- Focused regression: `45 passed`; repository statement coverage `100%` and
  branch coverage `98.61%`.
- AG Slice Gate: `2,540 passed`; aggregate statement coverage `98.93%` and
  branch coverage `96.60%`; restart smoke `14/14`.
- Fifth-Slice Checkpoint Gate: `12,535 passed`, `32 skipped`; aggregate
  statement coverage `98.94%` and branch coverage `97.46%`.
- Checkpoint scope coverage: signals, SLO evaluation, and alert lifecycle
  `100/100`; alert persistence statement `100%`, branch `98.61%`.
- Contract validation remained green with `168` schemas, `230` examples,
  `198` negative fixtures, and `7` OpenAPI documents.
