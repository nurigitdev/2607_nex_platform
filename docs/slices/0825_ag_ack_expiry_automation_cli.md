# Slice 0825: AG acknowledgement expiry automation CLI

## Objective

Provide an executable, bounded entry point that an external scheduler can call
without introducing an in-process loop or supervised subprocess.

## Behavior

- `--plan` is the default and returns a read-only tick plan.
- `--run-once --confirm-tick` executes at most one policy-bounded S82
  reconciliation cycle.
- Automation remains disabled by default. A disabled plan does not require a
  database connection.
- Enabled execution binds `SqlAlchemyOperatorReviewLivenessAckStateStore` to
  `NEX_AG_DATABASE_URL` with the existing AG worker pool settings.
- Protected smoke callers may explicitly select `NEX_AG_TEST_DATABASE_URL`;
  arbitrary database environment names are rejected.
- The SQLAlchemy engine is disposed after every CLI invocation.
- Output includes aggregate counts and environment-variable names only. It
  excludes database URLs, raw comments, and idempotency keys.
- No route, continuous loop, subprocess, or database table is added.

## Usage

```bash
PYTHONPATH=services/_shared:services/nex-ag \
  ./.venv/bin/python -m nex_ag.liveness_ack_expiry_automation_cli --plan --summary

NEX_AG_ACK_EXPIRY_AUTOMATION_ENABLED=1 \
PYTHONPATH=services/_shared:services/nex-ag \
  ./.venv/bin/python -m nex_ag.liveness_ack_expiry_automation_cli \
  --run-once --confirm-tick --summary
```

## Verification

```bash
./.venv/bin/pytest tests/test_nex_ag_liveness_ack_expiry_automation_cli.py -q --tb=short
```

Focused regression result: `12 passed`.

Full regression result: `5448 passed, 1 warning`.

- Statement coverage: `69481 / 70364 = 98.745096924564%`.
- Branch coverage: `16427 / 17078 = 96.188078229301%`.
- CLI module statement/branch coverage: `100% / 100%`.
