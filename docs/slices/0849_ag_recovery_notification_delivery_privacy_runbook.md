# Slice 0849: AG recovery notification delivery privacy and runbook evidence

## Objective

Freeze privacy regression and operator response guidance for the complete S85
delivery flow before closure.

## Privacy Hardening

The persisted S85 delivery metadata retains a safe request signature because it
is required to detect idempotency conflicts. That internal signature is now
recursively removed from both `NEW` and `REPLAYED` mutation responses. The
delivery read model and execution envelope continue to omit it.

The evidence injects raw credentials, database URLs, comments, idempotency
values, provider tokens, and provider payloads into source-only inputs. It
rejects any forbidden value or key that reaches public mutation, execution,
read-model, degraded, live-channel, or runbook surfaces.

## Operator Runbook

| Signal | Response |
| --- | --- |
| Confirmation required | Repeat only with explicit operator-approved confirmation. |
| Missing S85 marker | Reject the record and inspect its creation path. |
| Live channel blocked | Keep MOCK mode until a live-provider boundary is approved. |
| Idempotency conflict | Compare safe context; issue a new key only for a genuinely new request. |
| Provider retry wait | Wait for `next_attempt_at` and retain the bounded retry policy. |
| Completed delivery | Treat another targeted run as terminal `NOOP`. |
| Source unavailable | Restore the AG dispatch store before retrying. |
| PostgreSQL smoke failure | Verify cleanup and migrations before rerunning the smoke. |

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_ag_recovery_notification_delivery_privacy_runbook_evidence.py \
  --summary
./.venv/bin/pytest -q \
  tests/test_ag_recovery_notification_delivery_privacy_runbook_evidence.py \
  --cov=run_ag_recovery_notification_delivery_privacy_runbook_evidence \
  --cov-branch --cov-report=term-missing
```

Evidence result:

```text
ag_recovery_notification_delivery_privacy_runbook=pass surfaces=9 privacy=True signature=True runbook=True
```

- Focused privacy/API/execution regression: `29 passed, 1 warning`.
- Privacy/runbook runner statement/branch coverage: `100% / 100%`.
- Full regression: `5674 passed, 1 warning`.
- Statement coverage: `71071 / 71954` (`98.772827083970%`).
- Branch coverage: `16707 / 17358` (`96.249567922572%`).

The warning is the existing Starlette `TestClient` deprecation warning.
