# Slice 1449: S145 PostgreSQL Backup Worker

## Outcome

- Added a single-process, non-blocking lock per recovery-set run ID.
- Added atomically replaced mode-0600 state with attempts, five service
  outcomes, stale recovery, and partial quarantine counts.
- A fresh running owner is never preempted. A run becomes recoverable only
  after the fixed 30-minute stale window.
- Only `pg_dump_failed` and `backup_source_unavailable` retry. Backoff is
  bounded to one and two seconds, and the third attempt is terminal.
- Successful and failed run IDs replay their persisted result without
  executing backup work again.

## Safety Boundary

The state contains service IDs, statuses, timestamps, counts, and normalized
error codes only. It contains no database URL, password, backup path, row data,
or stderr. Lock and state files do not replace PostgreSQL advisory controls or
authorize restore, promotion, deletion, or production contact.

## Verification

- Focused tests: 22 passed.
- New worker and audit statement coverage: 100%.
- New worker and audit branch coverage: 100%.

## Handoff

Slice 1450 binds the worker to an opt-in single-host Docker Compose operator
profile and performs a deterministic five-service backup/recovery rehearsal.
