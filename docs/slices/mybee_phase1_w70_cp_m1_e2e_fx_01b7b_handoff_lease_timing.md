# CP-M1-E2E-FX-01B.7B: Synchronous Handoff Lease and Timing Evidence Hardening

## Purpose

The installed M1 Product journey reached an authoritative WC claim, but the
claim expired while the synchronous AE planning-before-ACK request was still
being retried. The historical 300-second claim lease was calibrated for the
former generation profile and did not provide enough observation margin after
the canonical generation provider moved from Qwen3.5-4B to Qwen3.5-9B.

This corrective Slice preserves synchronous planning-before-ACK and measures
the actual installed path before considering a larger architectural change.

## Decision

- Keep synchronous planning-before-ACK. A WC handoff is acknowledged only
  after AE has durably admitted planning and scheduling state.
- Set the installed WC claim lease to 600 seconds through
  `NEX_WC_CLAIM_LEASE_SECONDS`.
- Keep the AE claim-handoff HTTP timeout at 240 seconds.
- Require the configured lease to cover at least two handoff timeout windows.
- Treat 600 seconds as an empirical corrective baseline, not a permanent
  production SLO or a reason to hide provider latency.
- Do not add a database migration, queue, worker, fixture, or asynchronous ACK
  path.

## Implementation

- The installed assignment dispatcher validates the lease and passes it to the
  existing `WorkCoordinationService`.
- The event-delivery worker validates the same lease/timeout relationship and
  publishes both values in readiness evidence.
- The existing durable `service_log_entries` store now records every claimed
  delivery attempt with attempt count, result, error code, and elapsed
  milliseconds.
- Canonical Compose binds both WC processes to the same 600-second value.
- Canonical Compose admission rejects worker-to-worker lease drift or a lease
  shorter than two handoff timeout windows.
- The current process manifest admits the new environment contract for both
  WC processes.

## Verification

- Focused regression: `125 passed, 1 skipped`.
- WC Slice Gate: `744 passed, 26 skipped`.
- Actual `nex_wc_test` PostgreSQL restart/claim smoke: `1 passed`; the persisted
  active claim had an exact 600-second `created_at` to `lease_expires_at`
  interval and cleanup left zero tenant residue.
- WC statement coverage: `98.21%`.
- WC branch coverage: `95.99%`.
- `assignment_dispatch_process.py`: statement and branch `100%`.
- `event_delivery_process.py`: statement and branch `100%`.
- Contract validation, Golden Journey transition audit, and Demo product
  dependency audit: `PASS`.
- No PostgreSQL schema or API contract changed.

## Protected Live Rule

The actual M1 installed journey must be rerun only when the DGX is available
for a comparable Qwen3.5-9B observation window. The run must prove:

1. the authoritative claim is issued with a 600-second lease;
2. service logs contain non-zero handoff attempt timing evidence;
3. the synchronous planning request completes before claim expiry;
4. retry or failure remains fail-closed and observable;
5. the journey leaves no isolated-schema or container residue.

Until that protected run passes, this Slice closes the source and regression
boundary only; it does not close `CP-M1-E2E-FX-01B.7`.
