# Platform Observability and Incident Operations

## Purpose

This runbook operates the S148 metadata-only signal, SLI/SLO, alert,
notification, and NeX-AG dashboard path on the accepted single-host Docker
Compose topology. It covers local operations and protected staging evidence.
It does not authorize production deployment or claim that an external
notification endpoint is active.

## Safety Boundary

- OA, AE, CX, MO, and AG keep ownership of service data and service-local
  PostgreSQL. AG consumes only bounded API projections and signals.
- Prompts, source documents, generated text, vectors, credentials, endpoint
  URLs, complete database URLs, storage keys, and authorization values must
  never enter signals, alerts, receipts, dashboards, or evidence.
- Alert lifecycle and notification delivery are independent. Delivery failure
  never resolves or acknowledges the source alert.
- Missing or stale required telemetry is `NO_DATA`, never healthy.
- Mock transport success is `MOCK_ACCEPTED`, `BLOCKED`, and
  `EXTERNAL_NOT_ACTIVATED`; it is never live-delivery evidence.

## Delivery Modes

Set `NEX_NOTIFICATION_MODE` explicitly. The runtime must not probe internet
connectivity or silently downgrade modes.

| Mode | Operation | Required external control |
| --- | --- | --- |
| `local_only` | Durable AG workbench delivery only | None; host-loss detection remains unavailable. |
| `private_network` | Local delivery plus allowlisted internal HTTPS bridge | Managed TLS, secret reference, and an approved internal endpoint. |
| `internet_connected` | Local delivery plus allowlisted external HTTPS endpoint | Managed TLS, secret reference, approved endpoint, and protected live acceptance. |

The current accepted state is mock-only for private and internet delivery.
Operators must keep the dashboard activation field at
`EXTERNAL_NOT_ACTIVATED` until the activation checklist below passes.

## Startup and Readiness

1. Confirm the AG profile selects PostgreSQL and signed service/user trust.
2. Apply the NeX-AG migrations and verify `ag_alerts`, `ag_notify_outbox`, and
   `ag_notify_attempts` plus the `ix_ag_notify_claim` index.
3. Verify the configured notification mode and route aliases. Do not print
   endpoint or credential values.
4. Confirm AG readiness, the SLO policy digest, projection freshness, and the
   notification worker lease clock.
5. Open the protected AG dashboard and verify the external activation state.
6. Keep outbound delivery disabled if any required route, TLS, secret, or
   allowlist check is missing.

Deterministic checks:

```bash
./.venv/bin/python scripts/smoke/run_s148_observability_incident_boundary.py --summary
./.venv/bin/python scripts/smoke/run_s148_signal_correlation.py --summary
./.venv/bin/python scripts/smoke/run_s148_slo_evaluation.py --summary
./.venv/bin/python scripts/smoke/run_s148_alert_routing.py --summary
./.venv/bin/python scripts/smoke/run_s148_alert_persistence_restart.py --summary
./.venv/bin/python scripts/smoke/run_s148_mock_notification_delivery.py --summary
./.venv/bin/python scripts/smoke/run_s148_observability_api.py --summary
./.venv/bin/python scripts/smoke/run_s148_contract_mock_acceptance.py --summary
```

## Normal Operations

### SLI and SLO Triage

1. Start with the service, SLO ID, policy version, evaluation window, sample
   count, status, burn rate, owner, and runbook reference.
2. For `NO_DATA`, restore telemetry freshness before evaluating availability.
3. For `BREACHED`, correlate trace ID first and bounded correlation key second.
4. Follow the source-service runbook. Do not reconstruct private payloads from
   logs or request another service database directly.
5. Record an operator action only after confirming the current alert revision.

### Alert Lifecycle

- `FIRING` means the rule is active and has not been acknowledged.
- `ACKNOWLEDGED` records operator ownership; it does not stop evaluation.
- `SUPPRESSED` is time-bounded and requires a reason code. It preserves event
  history and does not imply recovery.
- `RESOLVED` requires a healthy evaluation or explicit recovery signal.
- Notification states `RETRY_WAIT`, `BLOCKED`, and `DEAD_LETTER` require
  transport triage while the alert remains independently visible.

Use acknowledgement for active ownership and suppression only for an approved
maintenance or duplicate-noise window. Never suppress missing telemetry merely
to make an SLO appear healthy.

### Notification Triage

1. Inspect channel, route alias, attempt count, safe result code, next attempt,
   and receipt digest.
2. Confirm one outbox item per idempotency hash and bounded lease ownership.
3. Retry only when the state and policy permit it. Terminal outcomes must not
   execute twice.
4. A mock 2xx response remains blocked from live activation.
5. Move exhausted work to `DEAD_LETTER`; preserve attempt history and alert
   state for operator review.

## Failure and Recovery

| Failure | Required response |
| --- | --- |
| AG API unavailable | Restore AG and PostgreSQL, then verify durable alert/outbox state before enabling workers. |
| PostgreSQL unavailable | Stop claims and mutations; recover the database before retrying delivery. |
| Worker lease stale | Wait for bounded lease expiry, claim once with a new worker ID, and verify idempotency. |
| Required signal stale | Project `NO_DATA`, restore the source projection, and re-evaluate the complete window. |
| Internal/external endpoint unavailable | Keep alert active, apply bounded retry, then block or dead-letter without fallback to an unapproved route. |
| Credential or TLS failure | Disable outbound claims, rotate through S143 custody, verify the route, and resume explicitly. |
| Alert storm | Verify grouping, debounce, inhibition, rate limits, and policy digest before suppressing. |
| AG restart | Rebuild repositories from PostgreSQL, recover expired leases, and verify dashboard counts before work resumes. |

After any restart, compare active alert, pending/retry/blocked notification, and
attempt counts before and after process recreation. A mismatch stops outbound
execution. Cleanup commands must target only evidence IDs created by the
current protected run.

## Protected PostgreSQL Acceptance

Run only against the service-owned test database. Inject the URL through the
environment; never put a value in source control, shell history, or reports.

```bash
NEX_AG_OBSERVABILITY_POSTGRES_SMOKE=1 \
NEX_AG_TEST_DATABASE_URL='<protected nex_ag_test URL>' \
./.venv/bin/python scripts/smoke/run_s148_observability_postgres.py --summary
```

Expected evidence is actual PostgreSQL on `nex_ag_test`, `18/18` checks, two
alerts, two notifications, three attempts, restart/API mutation success, and
zero residue. The external attempt must remain `MOCK_ACCEPTED` and `BLOCKED`.
The default Full Gate executes this runner without opt-in and therefore expects
an explicit skip; it does not silently reconnect to protected infrastructure.

## External Activation Checklist

All items are mandatory before changing `EXTERNAL_NOT_ACTIVATED`:

1. Endpoint ownership, delivery zone, allowlist, and incident contract are
   approved.
2. Endpoint and credential values are injected through S143 custody and are
   absent from PostgreSQL, logs, reports, and source control.
3. Managed TLS identity, certificate renewal, clock, and rollback pass.
4. Redacted payload, signature verification, deduplication, retry, outage,
   recovery, acknowledgement, and dead-letter paths pass protected acceptance.
5. The exact route configuration digest and SLO policy digest are recorded.
6. An owner, escalation policy, maintenance window, and last-known-good route
   are assigned.
7. S149 exercises the route under failure injection and S150 records approval.

Until then, local workbench delivery is the compensating control. A
time-bounded P1 waiver must identify owner, expiry, impact, rollback, and review
cadence; the codebase cannot grant that waiver implicitly.

## Single-Host Limitation

AG cannot report total power, host, storage, or network loss when it fails with
the same Compose host. Internet-connected operation needs an external
heartbeat/dead-man receiver. Private-network operation needs a separate
management node or monitoring appliance. `local_only` explicitly accepts the
absence of host-down paging and is not production host-loss evidence.

## Closure and S149 Handoff

Run closure and Full Gate:

```bash
./.venv/bin/python scripts/smoke/run_s148_observability_incident_closure.py --summary
./scripts/quality/run_quality_gate.sh
```

S149 consumes the exact policy digests, alert and delivery state, protected
PostgreSQL result, privacy contract, and unresolved external-activation state
for load, soak, failure injection, security, recovery, and rollback rehearsal.
Production deployment remains a separate S150 decision.
