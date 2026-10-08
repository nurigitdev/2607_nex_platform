# Slice 1480: S148 Observability PostgreSQL Smoke

## Outcome

- Added an opt-in protected smoke that migrates and connects directly to the
  actual `nex_ag_test` PostgreSQL database.
- Proved concise alert/outbox/attempt tables and claim index through the
  PostgreSQL catalog rather than SQLite DDL assumptions.
- Proved alert and outbox insert/select, local delivery, external mock retry,
  engine disposal/recreation, retry recovery, protected dashboard reads,
  acknowledgement, and suppression.
- Proved external mock acceptance remains `BLOCKED` plus `MOCK_ACCEPTED` and
  `EXTERNAL_NOT_ACTIVATED`, never a live delivery claim.
- Deleted the two smoke alerts through cascade cleanup and verified zero
  residue. Evidence contains only the database name and redacted URL metadata.

Slice 1481 publishes contracts/OpenAPI and negative privacy fixtures around
the now-proven runtime.

## Protected Evidence

- Database: actual `nex_ag_test`, backend `postgresql`.
- PostgreSQL smoke: `18/18`; `2` alerts, `2` notifications, `3` attempts,
  cleanup residue `0`.
- Focused regression: `6 passed`; smoke runner statement coverage `98.66%`,
  branch coverage `100%`.
- AG Slice Gate: `2,584 passed`; aggregate statement coverage `98.94%` and
  branch coverage `96.66%`.
- Contract validation: `168` schemas, `230` examples, `198` negative fixtures,
  and `7` OpenAPI documents.
