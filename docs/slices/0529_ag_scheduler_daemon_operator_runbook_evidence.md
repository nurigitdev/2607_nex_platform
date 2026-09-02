# Slice 0529: AG scheduler daemon operator runbook evidence

## Scope

- Add an operator runbook for AG scheduler daemon operations.
- Make protected PostgreSQL smoke execution explicit and distinguish default
  skipped smoke from live test DB evidence.
- Add a repository smoke that proves the runbook, S53 slice docs, quality-gate
  hook, daemon attention classification, and redaction guardrails remain wired.

## Implementation

- Added `docs/runbooks/ag_scheduler_daemon_operations.md` with default dashboard
  checks, protected smoke setup, manual tick-once guidance, attention states,
  and evidence checklist.
- Added `run_ag_scheduler_daemon_operator_runbook_evidence.py` to validate
  required files, runbook tokens, quality-gate registration, contiguous S53
  slice docs, and runbook redaction.
- Registered the runbook evidence runner in the default quality gate.

## Guardrails

- Runbook examples use redacted placeholders only.
- `start_daemon` and continuous loop execution remain blocked from AG.
- Protected smoke must be explicitly enabled and must target test databases.
- A skipped protected smoke remains "not executed", not live PostgreSQL proof.

## Evidence

```bash
./.venv/bin/pytest \
  tests/test_ag_scheduler_daemon_operator_runbook_evidence.py \
  -q --cov=run_ag_scheduler_daemon_operator_runbook_evidence \
  --cov-branch --cov-report=term-missing
```

The default quality gate now runs the runbook evidence check after the S53
boundary audit.
