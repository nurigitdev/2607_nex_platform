# nex-ag

Slice 0001 shell for NeX Admin and Governance.

Owned database env: `NEX_AG_DATABASE_URL`.

Current endpoints:

- `GET /health`
- `GET /ready`
- `GET /version`
- `GET /internal/v1/auth/service-claim`
- `GET /admin/v1/readiness/services`
- `GET /admin/v1/readiness/providers`
- `GET /admin/v1/generation-audit/generations/{cx_generation_id}`
- `GET /admin/v1/operations`
- `GET /admin/v1/operations/rollups`
- `GET /admin/v1/operations/dashboard`
- `GET /admin/v1/operations/issue-candidates`
- `GET /admin/v1/operations/event-taxonomy`
- `GET /admin/v1/operations/events`
- `GET /admin/v1/operations/events/{event_id}`
- `GET /admin/v1/operations/jobs`
- `GET /admin/v1/operations/jobs/{service_id}/{job_id}`
- `GET /admin/v1/operations/cx-processing-runs`
- `GET /admin/v1/operations/cx-processing-runs/{pipeline_run_id}`
- `GET /admin/v1/operations/retrieval-packages`
- `GET /admin/v1/operations/retrieval-packages/{retrieval_package_id}`
- `GET /admin/v1/operations/retrieval-score-calibration`
- `POST /admin/v1/operations/jobs/{service_id}/{job_id}/cancel`
- `POST /admin/v1/operations/jobs/{service_id}/{job_id}/retry`
- `GET /admin/v1/operations/sources`
- `GET /admin/v1/operations/traces/{trace_id}`
- `GET /admin/v1/operations/workers`
- `GET /admin/v1/operations/workers/{service_id}/{worker_id}`
- `GET /admin/v1/policies/retrieval`
- `GET /admin/v1/policies/retrieval/active`
- `GET /admin/v1/policies/retrieval/{policy_id}`

Provider readiness:

- AG reads MO's `GET /api/v1/provider-telemetry` with a service token and
  projects it into `ag_mo_provider_readiness_projection.v1`.
- The projection summarizes configured provider rows, request/success/failure
  counters, retryable failure counters, degraded counters, and the last safe
  failure metadata.
- In `live` mode, unconfigured provider rows are `NOT_READY`; observed provider
  failures or degraded counters are `DEGRADED`; telemetry fetch failures are
  `UNAVAILABLE`.
- Provider URLs, API keys, model paths, and raw upstream payloads are not copied
  into the AG projection.

Retrieval policy registry:

- AG exposes a read-only retrieval policy registry with current active policy
  `retrieval_quality_v1` and planned candidate policy
  `weighted_rrf_vector_bm25_v1`.
- Policy projections include versions, hashes, ranker weights, candidate limits,
  tokenizer profile metadata, confidence thresholds, and provider aliases.
- Policy projections also include `retrieval_threshold_decision.v1` checkpoint
  metadata. The current decision status is `OBSERVE`, so the canonical
  low-confidence threshold stays at `0.2` while additional live RAG score
  samples are collected.
- Policy mutation, publish, rollback, and audit are intentionally deferred.

Generation audit:

- AG assembles read-only generation audit projections through CX and AE service
  APIs. The projection includes safe generation summaries, progress timeline
  events, optional artifact handoff summaries, and an
  `ag_generation_audit_event.v1` event without raw prompts, provider paths,
  source text, generated output text, or storage paths.
- AG can also include an optional AE generation recovery request summary in the
  same projection, exposing requested action, policy hash status, dispatch
  target, attempt number, and retrieval reuse intent for failure audit.

Operational events:

- AG exposes a read-only operational event projection over the shared
  `operational_event.v1` shape.
- Filters include service id, severity, event type, trace id, text query `q`,
  `since`, `until`, `sort`, `cursor`, and limit.
- Event details are redacted by the shared runtime before AG projection.
- `GET /admin/v1/operations/events/{event_id}` returns
  `ag_operational_event_detail_projection.v1` for a single redacted event.
- AG also exposes a read-only event taxonomy projection so operators can inspect
  known event types, default severity, subject type, and safe detail keys.

Job operations:

- AG exposes a read-only job operations projection over the shared
  `common_job.v1` shape.
- Filters include service id, status, job type, `since`, `until`, `sort`,
  `cursor`, and limit.
- The projection summarizes active/terminal jobs, status counts, service
  counts, job-type counts, and per-service source availability.
- `GET /admin/v1/operations/jobs/{service_id}/{job_id}` returns
  `ag_job_operation_detail_projection.v1` for one service-scoped job and a
  lifecycle timeline assembled from matching operational events.
- `GET /admin/v1/operations/workers` returns
  `ag_worker_runtime_projection.v1` for worker heartbeat liveness across
  configured service sources.
- `GET /admin/v1/operations/workers/{service_id}/{worker_id}` returns
  `ag_worker_detail_projection.v1`, correlating the worker heartbeat with its
  active job and matching worker lifecycle operational events.
- Jobs and events can now be supplied through a shared operations source
  registry. Default runtime registration is still mock-first.
- Set `NEX_AG_OPERATIONS_SOURCE_MODE=postgres` to build a read-only registry
  from selected service databases. `NEX_AG_OPERATIONS_SOURCE_PROFILE` chooses
  `dev` or `test` database env names, and
  `NEX_AG_OPERATIONS_SOURCE_SERVICES` limits the observed service ids.
- PostgreSQL operations sources are wrapped as read-only so AG can list jobs
  and events without enqueueing jobs or appending event rows into service-owned
  databases.
- AG has a service-local job control HTTP client foundation for future operator
  actions. The client targets each service's `/internal/v1/jobs/...` routes,
  propagates request id and traceparent headers, and uses
  `NEX_AG_TO_<SERVICE>_SERVICE_TOKEN` when configured.
- AG exposes `cancel` and `retry` job operation endpoints. They return
  `ag_job_control_dispatch.v1` and preserve the service-local
  `service_job_control.v1` response under `service_response`.
- Job control dispatches emit AG-owned operational events:
  `ag.job_control.succeeded` or `ag.job_control.failed`. The audit write uses
  AG's local persistence store and never writes into target service databases.
- `NEX_AG_CROSS_SERVICE_OBSERVABILITY_SMOKE=1` runs a guarded test-profile
  smoke that creates CX processing job/event rows and verifies AG can observe
  them through `GET /admin/v1/operations`.
- `GET /admin/v1/operations/sources` exposes the current operations source
  runtime, selected service ids, source capability/read-only status, and safe
  redacted database env metadata. Source readiness statuses are
  `DEFAULT_MEMORY`, `READY`, or `NOT_CONFIGURED`.

Unified operations:

- AG exposes `GET /admin/v1/operations` as a combined read-only projection over
  jobs and operational events.
- Filters include service id, job status, job type, event severity, event type,
  trace id, `since`, `until`, `sort`, `cursor`, and limit.
- The response embeds the existing job and event projection shapes plus a
  combined summary and optional source registry summary.
- `GET /admin/v1/operations/traces/{trace_id}` returns
  `ag_cross_service_trace_timeline_projection.v1`, mixing matching jobs and
  events, structured service logs, and configured CX retrieval packages into
  one timestamped cross-service timeline.
- `GET /admin/v1/operations/rollups` returns
  `ag_operations_rollup_metrics_projection.v1`, aggregating per-service job
  and event totals plus source status counts for operator dashboards.
- `GET /admin/v1/operations/dashboard` returns
  `ag_operations_dashboard_snapshot_projection.v1`, combining source readiness,
  rollups, recent failed jobs/events, active jobs, CX processing run status
  summary, retrieval threshold decision readiness, and degraded source signals
  for the first AG operations dashboard screen.
- `GET /admin/v1/operations/issue-candidates` returns
  `ag_operations_issue_candidate_projection.v1`, applying deterministic
  read-only rules to operations dashboard signals, including retrieval
  threshold decision readiness. Notification delivery, acknowledgements, and
  incident mutation are intentionally deferred.
- AG remediation execution handoff planning is centralized in
  `nex_ag.generation_remediation_execution`. The planner maps CX remediation
  execution statuses back to AG task updates without bypassing the existing
  remediation transition policy, for example
  `PROPOSED -> IN_PROGRESS -> WAITING_ON_CX` after a CX `ACCEPTED` response.
  The same module also owns the dispatch service facade that loads an AG task,
  calls the injected CX remediation execution client, applies the planned task
  updates, and returns `ag_generation_remediation_execution_dispatch.v1`.
- `POST /admin/v1/generation-audit/generations/{cx_generation_id}/remediation-tasks/{remediation_action_id}/execute`
  is the protected AG dispatch API for sending a recorded AG remediation task
  to CX execution. It shares the existing remediation task store, updates task
  status through the planner, and supports safe `requested_at`, `planned_at`,
  and `idempotency_key` controls.
- `scripts/smoke/run_ag_remediation_execution_dispatch_postgres_smoke.py` is
  the guarded PostgreSQL test-profile evidence path for the dispatch API. It is
  skipped unless
  `NEX_AG_REMEDIATION_EXECUTION_DISPATCH_POSTGRES_SMOKE=1`, runs `nex-ag`
  migrations, writes one smoke task into `NEX_AG_TEST_DATABASE_URL`, dispatches
  it through the protected API with a static CX execution client, verifies the
  persisted `WAITING_ON_CX` state directly from PostgreSQL, and deletes the
  smoke row.
- `GET /admin/v1/operations/retrieval-packages` returns
  `ag_retrieval_package_operations_projection.v1`, a CX-sourced read-only
  projection of persisted retrieval packages for debugging grounded retrieval
  status, policy use, trace/request correlation, and low-confidence/no-answer
  outcomes without exposing raw source text or vector payloads. The projection
  includes a safe score-calibration summary comparing the persisted package
  score bucket with the active default retrieval threshold.
- `GET /admin/v1/operations/retrieval-packages/{retrieval_package_id}` returns
  `ag_retrieval_package_detail_projection.v1`, including safe evidence metadata
  such as ranks, hashes, score summaries, permission outcomes, and quality flags
  while redacting evidence text previews and principal ids. Detail responses
  include the same score-calibration record for threshold/debug review.
- `GET /admin/v1/operations/retrieval-score-calibration` returns
  `ag_retrieval_score_calibration_rollup_projection.v1`, a safe rollup/query
  surface over persisted CX retrieval package score-calibration records. It
  supports policy, status, action, default-bucket, threshold-override, trace,
  request, time-window, sort, cursor, and limit filters without live provider
  calls.
- `GET /admin/v1/operations/retrieval-threshold-decisions` returns
  `ag_retrieval_threshold_decision_projection.v1`, combining the retrieval
  policy registry threshold-decision checkpoint with persisted calibration
  samples so operators can see whether more live samples are required before
  reviewing canonical low-confidence threshold changes. Each decision includes
  `ag_retrieval_threshold_operator_review.v1` metadata with the canonical
  runbook id, remaining sample count, review paths, evidence requirements, and
  whether live-provider or policy-registry work is needed. The projection and
  dashboard section also include `ag_retrieval_threshold_calibration_closure.v1`
  so operators can see whether calibration is blocked, still collecting
  samples, waiting for review, or ready for policy review.
- The AG operations contract family also reserves
  `ag_cx_processing_run_operations_projection.v1` and
  `ag_cx_processing_run_detail_projection.v1` for CX processing run
  observability. These projections expose status, trace/request/job
  correlation, step counts, output refs, and error hashes without raw source
  text, markdown, chunks, summaries, vectors, prompts, or raw error details.
- `GET /admin/v1/operations/cx-processing-runs` and
  `GET /admin/v1/operations/cx-processing-runs/{pipeline_run_id}` are the
  read-only AG APIs for the same projection family. In PostgreSQL source mode,
  AG reads CX processing run and step rows without writing to the CX database.
- `scripts/smoke/run_ag_cx_processing_run_postgres_smoke.py` is the guarded
  PostgreSQL test-profile evidence path for the CX processing run list/detail
  APIs. It is skipped unless `NEX_AG_CX_PROCESSING_RUN_POSTGRES_SMOKE=1` and is
  included in the optional `run_postgres_test_smoke_suite.py` as
  `ag_cx_processing_run_postgres`.
- `scripts/smoke/run_ag_retrieval_package_postgres_smoke.py` is the guarded
  PostgreSQL test-profile evidence path for the retrieval package list/detail
  APIs and trace timeline correlation. It is skipped unless
  `NEX_AG_RETRIEVAL_PACKAGE_POSTGRES_SMOKE=1` and is included in the optional
  `run_postgres_test_smoke_suite.py` as `ag_retrieval_package_postgres`.
- `scripts/smoke/run_ag_retrieval_threshold_decision_postgres_smoke.py` is the
  guarded PostgreSQL test-profile evidence path for AG threshold-decision,
  dashboard, and issue-candidate reads over persisted CX retrieval package
  score samples. It is skipped unless
  `NEX_AG_RETRIEVAL_THRESHOLD_DECISION_POSTGRES_SMOKE=1` and is included in the
  optional `run_postgres_test_smoke_suite.py` as
  `ag_retrieval_threshold_decision_postgres`.
- The mock-first AG operations dashboard smoke covers the full operations
  endpoint family, including CX processing run list/detail visibility, and is
  included in `scripts/quality/run_quality_gate.sh`.
- Operations query pagination uses a non-negative integer `cursor` offset,
  returns `pagination.next_cursor` when more rows exist, and caps limit at the
  shared 500-row operations ceiling.
- The AG operations projection family is frozen under
  `contracts/schemas/service/nex_ag/operations_projection.v1.schema.json`, with
  positive examples in `contracts/examples/operations/`, negative examples in
  `contracts/tests/negative/operations/`, and route documentation in
  `contracts/openapi/nex-ag.openapi.yaml`.
  Retrieval package examples cover list, detail, and trace timeline correlation,
  including schema guards against raw evidence preview and principal id leakage.
