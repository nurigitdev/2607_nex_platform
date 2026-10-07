# Slice 1446: S145 Isolated Restore Guard

## Outcome

- Added strict manifest shape, archive size/hash, symlink, and `pg_restore
  --list` admission checks.
- Restore targets must use the policy target's exact `-recovery` libpq service
  and the `isolated_recovery` target class; the active source service cannot be
  selected.
- Executes a no-owner/no-ACL, single-transaction restore and requires database
  identity, migration head, `SELECT 1`, and extension probes.
- Keeps subprocess errors redacted and public evidence free of credential or
  physical path data.

## Handoff

Slice 1447 promotes successfully restored archives into a verified catalog,
quarantines incomplete runs, applies retention without deleting the last
verified point, and runs the fifth-Slice Checkpoint Gate.

