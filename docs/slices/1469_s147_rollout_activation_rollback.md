# Slice 1469: S147 Rollout Activation and Rollback

## Outcome

- Reused the existing catalog repository transaction for atomic alias
  activation and rollback instead of introducing a second routing store.
- Required a passing exact-revision canary, matching policy/metrics evidence,
  an active candidate reservation, and unchanged last-known-good lineage before
  promotion.
- Revalidated exact last-known-good readiness before rollback, restored its
  catalog binding, released candidate capacity, and retained candidate catalog
  and alias history.
- Added metadata-only activation and rollback results suitable for durable
  events without model names, endpoints, credentials, or payloads.

Slice 1470 persists the rollout and event stream in PostgreSQL, restores it
after restart, and exposes the metadata-safe operations projection.

## Verification

- Focused regression: `35 passed`; rollout state, activation, and smoke
  statement/branch coverage `100.00%`.
- MO Slice Gate: `1,204 passed`, `6 skipped`, statement `99.86%`, branch
  `99.36%`.
- Contract validation remained `166/228/196/7`; activation/rollback smoke
  passed all `12/12` checks.
