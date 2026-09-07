# Slice 0552: AE daemon CLI execute-mode contract/schema

## Scope

Define the AE artifact retention scheduler daemon CLI execute-mode command
contract while keeping the default CLI path plan-only.

## Decisions

- Execute mode is a separate schema-bound command envelope, not a change to the
  existing plan-only CLI plan.
- Execute commands require the `test` runtime profile, `enabled=true`,
  `explicit_opt_in=true`, and a bounded `max_cycles` value.
- The only supported execute mode is protected finite `bounded_loop`.
- The command marks database URL, process lock, and graceful shutdown handling as
  required for later execution slices, but it does not include database URLs,
  storage paths, raw artifact payloads, or secrets.
- Physical delete automation remains disabled by default.

## Evidence

- `services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py`
- `tests/test_nex_ae_artifact_retention_scheduler_daemon.py`
- `./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon.py -q`

## Next

- Slice 0553 adds process lock, pid, and run metadata contracts before wiring
  actual CLI execution.
