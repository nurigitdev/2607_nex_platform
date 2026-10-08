# Platform Observability, SLO, Alerting, and Incident Integration

Status: S148 active through Slice 1477. The boundary, redacted signal
correlation, service SLI/SLO evaluation, alert routing, and restart-safe
persistence are complete; protected PostgreSQL evidence and external endpoint
activation remain pending.

## Outcome

S148 turns the production-shaped signals completed by S143-S147 into one
metadata-only operations path owned by NeX-AG. It correlates metrics, logs, and
traces, evaluates service-level indicators and objectives, persists alert and
notification state, routes local and external delivery, and exposes a unified
operator projection. Production deployment remains unapproved.

## Non-Drift Boundary

- OA, AE, CX, MO, and AG keep ownership of their domain data and service-local
  PostgreSQL databases. AG consumes metadata-only service API projections.
- Cross-service database reads and foreign service-package imports remain
  prohibited.
- Alert detection is separate from notification delivery. A delivery failure
  never deletes, resolves, or silently acknowledges an alert.
- Prompts, documents, generated text, vectors, credentials, endpoint URLs, and
  private storage references are forbidden in observability and incident
  payloads. Opaque IDs, counts, timings, reason codes, and one-way digests are
  allowed.
- Existing operator-review escalation delivery remains case-specific. S148
  reuses its provider, retry, idempotency, and daemon patterns without making
  `ag_op_esc_dispatches` the source of record for platform alerts.
- Mock delivery is valid deterministic evidence. It does not activate or prove
  a production external notification endpoint.

## Signal and Correlation Contract

Every admitted signal has a stable signal ID, source service, signal kind,
signal name, UTC observation time, severity, status, trace/request correlation,
resource identity, numeric measurements, reason codes, and safe attributes.
The supported kinds are `METRIC`, `LOG`, `TRACE`, and `READINESS`.

Correlation uses `trace_id` first and a bounded `correlation_key` for signals
without a trace. It must preserve source service and timestamp ordering. A
missing source, stale observation, malformed trace, or privacy violation fails
closed. Correlation reports never recreate private payloads.

S148 consumes these production-shaped families:

| Owner | Signal families |
| --- | --- |
| OA | custody and federation readiness, signing failures, revocation and introspection health |
| AE | API and web readiness, session/auth denial rates, generation and artifact workflow health |
| CX | ingestion, index freshness, retrieval quality, generation and object-storage health |
| MO | capacity pressure, exact-revision readiness, calibration, canary, activation and rollback |
| AG | projection freshness, database health, alert evaluation, notification delivery and operator acknowledgement |
| Platform | TLS expiry, secret injection/rotation, PostgreSQL recovery, RustFS lifecycle and Compose process health |

## SLI and SLO Policy

SLIs are evaluated over explicit UTC windows with a numerator, denominator,
unit, aggregation, freshness limit, and minimum sample count. Every SLO names
one accountable owner, a target, a warning and critical burn-rate policy, and a
runbook reference. Missing or stale mandatory telemetry is `NO_DATA`, never a
passing measurement.

The initial service objectives are configuration-backed defaults, not
unreviewable constants:

| Service | Required SLI families |
| --- | --- |
| nex-oa | availability, authentication success, signing latency, custody freshness |
| nex-ae-api | availability, request success, workflow completion latency, session denial correctness |
| nex-cx | availability, ingestion success, index freshness, retrieval no-answer and generation quality |
| nex-mo | availability, provider error rate, p95 latency, GPU headroom, calibration validity |
| nex-ag | availability, projection freshness, alert evaluation latency, notification delivery success |

Policy changes are versioned and digest-bound. S150 approval consumes the exact
active policy set. S149 owns production-sized load, soak, and threshold tuning.

## Alert Lifecycle and Routing

Alert state is `PENDING -> FIRING -> ACKNOWLEDGED -> RESOLVED`, with explicit
`SUPPRESSED` handling that cannot erase history. Evaluation groups repeated
signals by tenant, service, rule, resource, and incident window. Deduplication,
debounce, inhibition, and rate limits prevent alert storms while recovery
notifications remain explicit.

Routing considers severity, accountable team, environment class, delivery
zone, quiet-hours policy, acknowledgement, and escalation age. `CRITICAL`
production alerts require a ready paging route for S150 admission. An
unconfigured or unhealthy required route is `BLOCKED`, not successful.

## Delivery Zones

Connectivity is selected explicitly by `NEX_NOTIFICATION_MODE`; runtime code
must not infer it by probing the public internet or silently downgrade it.

| Mode | Delivery behavior | S148 evidence |
| --- | --- | --- |
| `local_only` | Durable AG workbench notification and operator acknowledgement; no outbound endpoint | deterministic and PostgreSQL protected evidence |
| `private_network` | Local delivery plus allowlisted internal HTTPS webhook, SMTP, SIEM, or incident bridge | controlled loopback/internal endpoint evidence |
| `internet_connected` | Local delivery plus allowlisted external HTTPS notification or incident endpoint | mock evidence now; protected live activation later |

The first external transport is a provider-neutral signed HTTPS webhook. A
provider-specific SaaS adapter is optional and must remain behind the same
contract. Endpoint and credential values come from S143 secret/TLS references;
only endpoint aliases and configuration digests may be persisted or exported.

The current S148 environment has no approved external notification or incident
endpoint. Its honest acceptance state is `MOCK_ACCEPTED` with
`EXTERNAL_NOT_ACTIVATED`. Mock success must never be projected as live delivery.

## Durable Alert and Notification State

The concise AG-owned tables are `ag_alerts`, `ag_notify_outbox`, and
`ag_notify_attempts`. Their names remain below PostgreSQL's identifier limit.
The outbox is restart-safe, transactionally linked to alert transitions, and
claimed with bounded leases. Delivery states are `PENDING`, `CLAIMED`,
`DELIVERED`, `RETRY_WAIT`, `BLOCKED`, and `DEAD_LETTER`.

Every notification has an idempotency hash, route alias, payload hash, attempt
count, next-attempt time, safe result code, and receipt digest. Backoff is
bounded. A terminal delivery outcome cannot be executed twice. Operator
acknowledgement is separate from transport receipt.

## Integrated AG Operations Surface

AG exposes protected metadata-only projections for:

- current SLI/SLO status and burn rate by service;
- firing, acknowledged, suppressed, and recently resolved alerts;
- signal correlation and trace linkage;
- delivery readiness, queued work, retries, blocked routes, and dead letters;
- accountable owner and runbook reference;
- local acknowledgement and suppression actions with audit events.

The operations dashboard is a projection, not another source of record. It
must show `EXTERNAL_NOT_ACTIVATED` while only mock delivery is available.

## Single-Host Limitation

The Compose host can report component failures only while AG, PostgreSQL, and
the host network remain alive. It cannot emit its own total power, host, or
network-loss alert. Internet-connected operation requires an external
heartbeat/dead-man receiver for host-loss detection. Private-network operation
requires a separate management node or monitoring appliance. `local_only`
accepts this limitation explicitly; it is not production host-down evidence.

## Acceptance and Privacy

- Deterministic regression proves all delivery modes, routing decisions,
  retries, deduplication, acknowledgement, suppression, recovery, and privacy.
- Protected S148 evidence uses the actual `nex_ag_test` database and proves
  migration, insert/select/update, restart reconstruction, lease recovery,
  cleanup, and zero residue.
- Because no external endpoint is prepared, outbound acceptance uses mock and
  controlled loopback transports. Live external activation remains visible as
  an unresolved production control for S150 unless an approved endpoint is
  supplied and protected acceptance passes.
- Evidence is metadata-only and must not contain secrets, endpoints, private
  content, authorization values, database URLs, or process commands.

## Slice Sequence

| Slice | Outcome |
| --- | --- |
| `1473` | Freeze the signal, SLI/SLO, alert, delivery-zone, persistence, privacy, single-host, and acceptance boundary. |
| `1474` | Implement the common redacted signal envelope and metric/log/trace correlation. |
| `1475` | Implement service-owned SLI/SLO policies, window evaluation, burn rate, and no-data semantics. |
| `1476` | Implement alert lifecycle, grouping, deduplication, suppression, and routing decisions. |
| `1477` | Persist alert/outbox/attempt state, prove restart recovery, and run Checkpoint Gate. |
| `1478` | **Complete.** Implemented local, private-network, and internet-connected mock delivery with retry and receipts. |
| `1479` | **Complete.** Wired protected AG APIs and the integrated operations/dashboard projection. |
| `1480` | **Complete.** Ran actual `nex_ag_test` migration, restart-safe processing, and zero-residue protected smoke. |
| `1481` | Publish schemas/OpenAPI, privacy fixtures, mock incident acceptance, and operations evidence. |
| `1482` | Publish the runbook, bind closure evidence, run Full Gate, close S148, and activate S149. |

Checkpoint Gate runs at Slice 1477. Full Gate runs at Slice 1482.

## S149 and S150 Handoff

S149 consumes exact SLI/SLO policies, alert routing, persistence, delivery
readiness, and incident evidence for load, soak, failure injection, security,
and recovery rehearsal. S150 requires explicit SLO ownership and either a
protected live external endpoint or an approved time-bounded P1 waiver with a
local compensating control. Neither S148 nor a passing mock transport performs
an implicit production deployment.
