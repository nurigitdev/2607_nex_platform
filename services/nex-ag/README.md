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
- `GET /admin/v1/operations/artifacts`
- `GET /admin/v1/operations/artifact-retention/automation`
- `GET /admin/v1/operations/artifact-retention/batch-plan`
- `GET /admin/v1/operations/artifact-retention/scheduler-daemon-operator-control-execution-worker-result-diagnostics`
- `GET /admin/v1/operations/artifacts/{artifact_id}`
- `GET /admin/v1/operations/artifacts/{artifact_id}/lifecycle`
- `POST /admin/v1/operations/jobs/{service_id}/{job_id}/cancel`
- `POST /admin/v1/operations/jobs/{service_id}/{job_id}/retry`
- `GET /admin/v1/operations/sources`
- `GET /admin/v1/operations/traces/{trace_id}`
- `GET /admin/v1/operations/workers`
- `GET /admin/v1/operations/workers/{service_id}/{worker_id}`
- `GET /admin/v1/operator-review/notes`
- `GET /admin/v1/operator-review/notes/{operator_note_id}`
- `POST /admin/v1/operator-review/notes`
- `GET /admin/v1/operator-review/workbench`
- `GET /admin/v1/operator-review/workbench/rollups`
- `GET /admin/v1/operator-review/evidence-exports`
- `GET /admin/v1/operator-review/evidence-exports/{export_id}`
- `POST /admin/v1/operator-review/evidence-exports`
- `GET /admin/v1/policies/retrieval`
- `GET /admin/v1/policies/retrieval/active`
- `GET /admin/v1/policies/retrieval/{policy_id}`
- `POST /admin/v1/generation-audit/generations/{cx_generation_id}/remediation-tasks/{remediation_action_id}/sync-execution-status`

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
- `GET /admin/v1/operations/artifacts` returns
  `ag_artifact_operation_collection_projection.v1`, reading the owner-scoped
  AE artifact collection through the AE client boundary and preserving only
  metadata-safe ids, statuses, routes, counts, target formats, hashes, and
  quality summaries.
- `GET /admin/v1/operations/artifacts/{artifact_id}` returns
  `ag_artifact_operation_detail_projection.v1` for one AE artifact and optional
  handoff/chat artifact link context without exposing rendered content or local
  storage paths.
- `GET /admin/v1/operations/artifacts/{artifact_id}/lifecycle` returns
  `ag_artifact_operation_lifecycle_projection.v1`, deriving metadata-only
  archive, restore, and logical delete availability from the AE artifact's
  current status without mutating AE state.
- Slice 0450 closes S45 by checking the AG artifact collection projection
  remains connected to the AE-owned collection API and AE Web library evidence
  without crossing the metadata-only operations boundary.
- Slice 0451 starts S46 by freezing AG's lifecycle role as read-only operator
  projection and issue-candidate generation. AE remains the lifecycle mutation
  owner, while AG may surface `ARCHIVE`, `RESTORE`, and logical `MARK_DELETED`
  state only through metadata-safe AE artifact projections.
- Slice 0460 closes S46 by checking AG's lifecycle projection stays read-only,
  metadata-only, and connected to the AE artifact lifecycle surface alongside
  the AE Web lifecycle evidence.
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
- `HttpCxRemediationExecutionClient.get_remediation_execution_detail(...)` and
  `sync_generation_remediation_execution_status(...)` form the AG status
  follow-up foundation after dispatch. AG reads the CX
  `cx_remediation_execution_detail.v1` projection, validates the embedded
  execution result, can inspect the safe
  `cx_repaired_generation_lineage.v1` parent/action/repair link, maps CX
  execution status back to the AG remediation task state machine, and keeps
  same-status sync idempotent.
- `POST /admin/v1/generation-audit/generations/{cx_generation_id}/remediation-tasks/{remediation_action_id}/sync-execution-status`
  is the protected AG status sync API for reconciling a dispatched task from
  CX execution detail. It returns
  `ag_generation_remediation_execution_status_sync.v1`, preserves
  `UPDATED`/`UNCHANGED` sync outcomes, and shares the dispatch route's service
  authorization boundary.
- `scripts/smoke/run_ag_remediation_execution_dispatch_postgres_smoke.py` is
  the guarded PostgreSQL test-profile evidence path for the dispatch API. It is
  skipped unless
  `NEX_AG_REMEDIATION_EXECUTION_DISPATCH_POSTGRES_SMOKE=1`, runs `nex-ag`
  migrations, writes one smoke task into `NEX_AG_TEST_DATABASE_URL`, dispatches
  it through the protected API with a static CX execution client, verifies the
  persisted `WAITING_ON_CX` state directly from PostgreSQL, and deletes the
  smoke row.
- `scripts/smoke/run_ag_remediation_execution_status_sync_postgres_smoke.py`
  is the guarded cross-database PostgreSQL test-profile evidence path for the
  status sync API. It is skipped unless
  `NEX_AG_REMEDIATION_EXECUTION_STATUS_SYNC_POSTGRES_SMOKE=1`, runs both
  `nex-ag` and `nex-cx` migrations, reads CX execution detail from
  `NEX_CX_TEST_DATABASE_URL`, updates the AG task in
  `NEX_AG_TEST_DATABASE_URL`, verifies both rows directly from PostgreSQL, and
  deletes both smoke rows.
- Slice 0370 closes the S37 remediation runtime integration track with a
  quality gate checker covering CX execution evidence, AG dispatch, CX
  read-model follow-up, AG status sync, and optional PostgreSQL smoke suite
  wiring.
- `nex_ag.remediation_runtime_audit` records
  `ag_remediation_runtime_operations_gap_audit.v1`, the S38 entry checkpoint
  for remediation execution operations. It keeps AG as the owner of
  operator-facing remediation execution operations and status-sync scheduling,
  keeps CX as the owner of execution attempts and repair lineage, and freezes
  the `0372` through `0377` gap order before adding new operations APIs or
  status-sync workers.
- `nex_ag.remediation_execution_operations` builds
  `ag_remediation_execution_operations_projection.v1`, a read-only AG
  operations projection that merges AG remediation tasks with CX remediation
  execution attempts by `remediation_action_id`. It reports safe sync states
  such as `NO_EXECUTION`, `ORPHAN_EXECUTION`, `IN_SYNC`, and `SYNC_REQUIRED`
  without exposing raw prompt/output/source/evidence text or credential
  material.
- `GET /admin/v1/operations/remediation-executions` exposes that projection
  through the protected AG operations API. It supports filters for
  `cx_generation_id`, `remediation_action_id`, AG `action_status`, CX
  `execution_status`, trace/request ids, and the shared time/pagination
  controls.
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
- `GET /admin/v1/operations/remediation-executions` exposes the read-only AG/CX
  remediation execution projection, and the unified dashboard now includes a
  `remediation_executions` section plus
  `remediation_execution_attention_required.v1` issue candidates for failed,
  orphan, missing, unknown, or status-sync-required execution records.
- `nex_ag.remediation_execution_status_sync_jobs` plans deterministic
  `common_job.v1` records for AG-owned remediation execution status sync. The
  planner queues only `SYNC_REQUIRED` records with trace/request correlation,
  blocks operator-review states, reuses AG/CX debug links, and keeps raw
  prompt/output/source/evidence text and provider/runtime secrets out of job
  payloads.
- `nex_ag.remediation_execution_status_sync_worker` runs those status-sync
  jobs through the shared worker runner. It validates job shape and correlation,
  emits heartbeat/log evidence through injected runtime stores, delegates the
  task update to `sync_generation_remediation_execution_status(...)`, and
  returns only a redacted worker result summary.
- `scripts/smoke/run_ag_remediation_execution_status_sync_worker_postgres_smoke.py`
  is the guarded cross-database PostgreSQL test-profile evidence path for the
  AG status-sync worker. It is skipped unless
  `NEX_AG_REMEDIATION_EXECUTION_STATUS_SYNC_WORKER_POSTGRES_SMOKE=1`, runs
  `nex-ag` and `nex-cx` migrations, enqueues an AG status-sync job, claims it
  through the worker runtime, verifies AG task/job/heartbeat/log rows and the
  CX execution row directly from PostgreSQL, and cleans up smoke rows.
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
- Slice 0479 adds
  `ag_artifact_operation_retention_history_projection.v1` and
  `GET /admin/v1/operations/artifact-retention/executions`. AG reads the AE
  retention execution history collection through the artifact operations client,
  summarizes mode/status/deletion counts for operators, and keeps raw persisted
  execution JSON out of the operations projection.
- Slice 0480 closes S48 with an automated checkpoint confirming the AG
  retention history projection remains linked to AE history read-model/query
  evidence while preserving read-only, metadata-only operator semantics.
- Slice 0481 starts S49 by freezing AG's role for scheduled artifact retention
  operations: AG may expose operator projection and future dispatch controls
  through AE APIs, but it must not write directly into the AE artifact database.
- Slice 0488 adds
  `ag_artifact_operation_retention_batch_projection.v1` and
  `GET /admin/v1/operations/artifact-retention/batch-plan`. AG reads AE's
  owner-scoped batch plan through the AE client boundary, summarizes scheduler
  status, candidate counts, selected counts, estimated delete counts, and
  dispatch availability, and keeps the projection metadata-only.
- Slice 0489 connects that projection to protected AE PostgreSQL smoke evidence:
  the smoke builds a live-test-DB batch plan, scheduled command, mock-worker
  history row, and AG batch projection without any direct AG write into AE
  persistence.
- Slice 0490 closes S49 by checking AG's batch-plan projection stays connected
  to AE's scheduled retention boundary, schedule contract, batch plan API,
  scheduled command, mock worker, and PostgreSQL smoke evidence while remaining
  read-only and metadata-only.
- Slice 0491 starts S50 by freezing AG's scheduler-runtime role. AG may project
  scheduled retention jobs and later dispatch controls through AE APIs, but it
  must not enqueue jobs directly in AE persistence or write to the AE artifact
  database.
- Slice 0496 adds a metadata-only AG projection for AE artifact retention
  scheduled jobs at `/admin/v1/operations/artifact-retention/scheduled-jobs`.
  It reports common JobQueue status, retry attention, safe AE route links, and
  retention estimates while keeping AE as the system of record.
- Slice 0497 adds a protected AG dispatch guardrail at
  `/admin/v1/operations/artifact-retention/scheduled-jobs/dispatch`. Operators
  must set `confirm_dispatch=true`; AG rechecks the AE batch plan, then calls
  the AE scheduled-job admission route without directly enqueueing AE jobs.
- Slice 0498 closes the source-route gap on the AE side. AG scheduled job
  operations can now point at AE's protected scheduler config, scheduled-job
  list, and scheduled-job admission APIs while keeping AG read-only against AE
  persistence.
- Slice 0499 adds protected cross-service PostgreSQL smoke evidence for the
  scheduled retention operator path. The smoke drives AG's dispatch and list
  routes against an AE TestClient backed by the real AE test DB, proves AG does
  not write AE persistence directly, verifies the queued job through
  `service_jobs`, and emits only metadata/redacted evidence.
- Slice 0500 closes S50 by checking AG's scheduled job projection and dispatch
  guardrail stay connected to AE's scheduler config/read-model APIs,
  JobQueue-backed admission, worker runtime evidence, and AE-only persistence
  ownership.
- Slice 0501 starts S51 by freezing AG's retention automation boundary. AG may
  project and dispatch AE retention automation through protected AE APIs, but it
  still cannot write AE persistence or enqueue AE jobs directly.
- Slice 0509 adds
  `ag_artifact_operation_retention_automation_projection.v1` at
  `/admin/v1/operations/artifact-retention/automation`. AG combines AE batch
  plan, scheduled-job, and retention-history read models into one metadata-only
  operator summary while keeping physical delete automation disabled and
  operator approval visible.
- Slice 0510 closes S51 by checking AG's automation projection stays connected
  to AE scheduler tick admission, protected PostgreSQL smoke evidence, physical
  purge approval guardrails, and read-only/metadata-only operator semantics.
- Slice 0511 starts S52 by freezing AG's scheduler-daemon operations boundary.
  AG may later project lease, last tick, and queue posture through AE APIs, but
  daemon control remains AE-owned and AG still performs no direct database write
  or direct job enqueue.
- Slice 0516 keeps that boundary explicit by introducing AE-owned
  daemon config/control contracts. AG can project the metadata-only decision
  surface later, while `start_daemon` remains blocked and manual tick-once
  readiness depends on AE lease and JobQueue posture.
- Slice 0517 adds the AE dispatch facade behind that control surface. AG still
  should call AE APIs rather than touching JobQueue or database state directly;
  blocked/no-op controls stay metadata-only and manual tick-once remains
  lease-protected.
- Slice 0518 makes that surface callable through AE-owned API routes. AG can
  later project or invoke the control route, but the route preserves AE
  ownership over leases, JobQueue dispatch, artifact store access, and history.
- Slice 0519 proves that boundary against PostgreSQL: the protected smoke drives
  the AE daemon config/control routes with the real AE test DB and validates
  lease, JobQueue, and history readback without any AG direct database writes.
- Slice 0520 closes S52 with AG still on the read-only side of the boundary:
  daemon control stays AE-owned, and AG should use AE routes for visibility or
  operator-mediated manual tick-once dispatch.
- Slice 0521 starts S53 by freezing AG's scheduler-daemon operations boundary.
  AG may project daemon config/control state and later request manual
  tick-once through AE APIs, but AG still cannot write AE persistence or enqueue
  AE retention jobs directly; `start_daemon` and continuous loop execution stay
  blocked/deferred.
- Slice 0522 adds the AG-side AE scheduler daemon client adapter. AG can now
  fetch daemon config and submit daemon control requests through AE API
  transport while route policy and operator dispatch guardrails remain staged
  for later S53 slices.
- Slice 0523 adds the AG scheduler daemon operations projection. The projection
  summarizes AE daemon runtime, lease repository, JobQueue readiness, supported
  action decisions, and optional dispatch outcomes as metadata-only operator
  evidence while redacting persistence/storage internals.
- Slice 0524 exposes that projection at
  `/admin/v1/operations/artifact-retention/scheduler-daemon`. The route is
  protected, read-only, and delegates daemon state reads to AE's daemon config
  API through the AG client adapter.
- Slice 0525 adds the protected AG manual tick-once route at
  `/admin/v1/operations/artifact-retention/scheduler-daemon/manual-tick-once`.
  Operators must send `confirm_dispatch=true`; `start_daemon` and continuous
  loop actions remain blocked, and `run_worker=true` requires an additional
  `confirm_worker_run=true` guard.
- Slice 0526 proves the guarded AG-to-AE daemon flow against PostgreSQL test
  evidence. The smoke drives AG routes, confirms AG used AE daemon source
  routes, and validates that lease, JobQueue, history, and artifact persistence
  effects remain AE-owned and metadata-only from AG.
- Slice 0527 rolls scheduler daemon posture into the existing artifact
  retention automation dashboard. Operators can see manual tick-once readiness,
  daemon start blocking, lease repository availability, and JobQueue readiness
  in the dashboard without giving AG direct write or enqueue authority.
- Slice 0528 classifies that daemon posture into AG operator attention states:
  ready, lease attention, queue attention, batch-window attention, policy
  blocked, and latest-dispatch review. The classification is metadata-only and
  keeps daemon execution decisions in AE.
- Slice 0529 adds the AG scheduler daemon operations runbook and repository
  evidence check. The runbook separates default metadata-only dashboard proof
  from protected PostgreSQL smoke evidence and keeps all secrets redacted.
- Slice 0530 closes S53 with a quality-gate closure check for the AG daemon
  operations chain, including AE-owned control, guarded manual tick-once,
  dashboard rollup, attention classification, runbook evidence, and protected
  PostgreSQL smoke references.
- Slice 0531 starts S54 by freezing the AE scheduler daemon runtime enablement
  boundary before any continuous loop is opened. AG remains read-only for daemon
  runtime state, may request controls only through AE APIs, and must wait for
  AE-owned config, loop planning, one-cycle smoke evidence, and heartbeat
  metadata before adding richer runtime projections.
- Slice 0532 adds AE's runtime config expansion for that daemon. AG can later
  project the metadata-only profile, opt-in, interval, jitter, lease, and
  batch-window posture, but runtime enablement decisions, daemon start/stop,
  lease state, JobQueue dispatch, and artifact persistence effects remain
  AE-owned.
- Slice 0533 adds AE's pure daemon loop planner. AG may later display the
  disabled, blocked, no-op, or ready decision as operator evidence, but the
  planner performs no lease acquisition, JobQueue enqueue, worker execution,
  history write, daemon start, or continuous loop start.
- Slice 0534 adds AE's one-cycle daemon runner adapter. AG can later project
  the adapter result, but one-cycle execution, lease acquisition, JobQueue
  enqueue, worker execution, and history effects remain behind AE-owned
  runtime APIs and still do not start a continuous daemon loop.
- Slice 0535 exposes AE's start/stop control guardrail through AG projection.
  AG can show metadata-only `start_daemon` blocked and `stop_daemon` no-op
  evidence, while daemon state mutation, stop signals, leases, JobQueue work,
  history writes, and continuous loop execution remain AE-owned and disabled.
- Slice 0538 projects AE scheduler daemon runtime heartbeat observation into
  AG operations. AG fetches AE's read-only runtime route, summarizes heartbeat
  status and store availability for operators, treats runtime fetch failures as
  degraded warning evidence, and still leaves all daemon runtime persistence and
  execution authority in AE.
- Slice 0539 makes that runtime observation actionable. AG now classifies
  heartbeat-store unavailability, `ERROR` heartbeats, and unknown heartbeat
  statuses as `HEARTBEAT_ATTENTION`, and emits metadata-only runtime issue
  candidates while preserving normal `BUSY`/`IDLE` and latest-dispatch behavior.
- Slice 0540 closes S54 by registering the AE scheduler daemon runtime closure
  evidence in the default quality gate. AG remains read-only and metadata-only
  for AE daemon runtime state, while runtime attention and issue candidates are
  covered by closure checks.
- Slice 0541 starts S55 by freezing the AE daemon process boundary. AG can
  observe AE-owned process/runtime state and request AE-owned controls, but AG
  still cannot write AE persistence, enqueue AE jobs directly, or host the
  daemon coordinator.
- Slice 0542 defines the AE-owned daemon runtime state snapshot that AG can later
  project as metadata-only lifecycle evidence without gaining write access to AE
  persistence or JobQueue admission.
- Slice 0548 adds that AG lifecycle projection. AG now preserves AE runtime
  state, bounded-loop, shutdown, and retry-circuit metadata in its daemon
  operations response while keeping daemon process control, persistence writes,
  JobQueue admission, and physical purge authority inside AE.
- Slice 0549 hardens the protected AE/AG daemon PostgreSQL smoke so it writes a
  DB-backed AE daemon heartbeat, reads it through the AG operations route, and
  verifies lifecycle `RUNNING` projection plus cleanup against the AE test DB.
- Slice 0550 closes S55 by adding a default quality-gate closure audit for the
  AE daemon process/lifecycle boundary. AG remains read-only and metadata-only
  for lifecycle projection, while AE retains daemon process ownership,
  persistence writes, JobQueue admission, and physical purge authority.
- Slice 0551 starts S56 by freezing the executable daemon runtime boundary from
  the AG side. AG may observe protected bounded-loop execution evidence through
  AE APIs, but it still cannot start the process directly, write AE
  persistence, enqueue AE jobs, or receive unredacted daemon/runtime payloads.
- Slice 0552 keeps that AG boundary unchanged while AE defines its execute-mode
  CLI command envelope. AG may later project safe command metadata, but
  execution authority, database URLs, process locking, JobQueue admission, and
  physical purge policy remain AE-owned.
- Slice 0553 keeps process lock, pid, and daemon run metadata AE-owned and
  metadata-only. AG may consume safe lifecycle summaries later, but it still
  cannot acquire locks, persist run records, enqueue AE jobs, or receive raw
  daemon/runtime payloads.
- Slice 0554 keeps graceful shutdown signal handling AE-owned. AG may later
  observe safe signal/shutdown transition summaries, but it cannot install
  handlers, deliver stop signals, terminate AE processes, persist lifecycle
  state, or enqueue AE retention work.
- Slice 0555 keeps bounded-loop CLI execution AE-owned. AG may later read the
  redacted execution-result envelope, but it still cannot provide execution
  dependencies, acquire locks, run bounded loops, enqueue AE jobs, persist AE
  lifecycle records, or access raw runtime payloads.
- Slice 0556 keeps the executable smoke proof AE-owned as well. The protected
  PostgreSQL smoke emits only redacted CLI execution metadata for future AG
  projection; AG still cannot trigger the smoke, receive database URLs, acquire
  daemon process locks, or write AE lifecycle state.
- Slice 0557 gives AG a future read-model target without adding write authority:
  AE persists redacted daemon run/event summaries in its own database, while AG
  may later project those rows only through AE-owned service APIs.
- Slice 0558 opens that AE-owned service API target. AG can now call the
  read-only daemon run collection/detail routes in a later projection slice,
  but it still cannot write AE daemon run rows, enqueue AE retention jobs, or
  receive raw daemon execution payloads.
- Slice 0559 adds that AG projection. AG exposes read-only
  `/admin/v1/operations/artifact-retention/scheduler-daemon-runs` collection
  and detail routes backed by AE API calls, summarizes safe run/lifecycle
  metadata, and proves the route path against rows written to the AE test DB by
  a protected PostgreSQL smoke.
- Slice 0560 closes S56 by registering the executable runtime closure in the
  quality gate. AG's final S56 responsibility is read-only daemon run
  projection over AE APIs; process control, persistence writes, and JobQueue
  admission remain AE-owned.
- Slice 0561 starts S57 by freezing AG's supervisor operations boundary. AG may
  project AE supervisor status and guarded outcomes later, but it must still
  call AE APIs only and cannot write AE daemon persistence, enqueue AE retention
  jobs, or control local daemon processes directly.
- Slice 0562 keeps that AG boundary unchanged while AE defines the supervisor
  command/result contracts. AG can later display `status_probe`, blocked
  `start_daemon`, and no-op `stop_daemon` outcomes, but the contract performs
  no process control or AE database writes.
- Slice 0563 keeps AG read-only while AE adds the fake/dry-run supervisor
  adapter foundation. AG may later distinguish no-adapter and fake-adapter
  outcomes from AE evidence, but process execution remains AE-owned and still
  side-effect free.
- Slice 0564 gives AG a future supervisor read-model target without write
  authority. AE persists supervisor result/event summaries in its own database;
  AG may later project those rows through AE APIs only and still cannot control
  AE daemon processes, enqueue AE jobs, or write AE persistence directly.
- Slice 0565 opens that AE API target. AG can later call the supervisor
  control/result routes for safe evidence projection, but process control,
  persistence writes, JobQueue admission, and physical delete automation remain
  AE-owned.
- Slice 0566 proves that target against AE PostgreSQL test storage. The smoke
  is still AE-owned and protected, but it gives the later AG projection a
  migration/readback/cleanup baseline for supervisor record and event evidence.
- Slice 0567 adds the AG read-only projection foundation over that AE
  supervisor read model. AG can summarize safe supervisor outcomes through
  in-memory and HTTP client adapters, but it still cannot control AE daemon
  processes, enqueue AE retention jobs, write AE persistence, or expose raw
  command/result payloads.
- Slice 0568 exposes that supervisor projection through AG admin read-only
  routes for collection and detail views. AG validates service/action/status
  filters locally, then calls AE APIs only; process control, JobQueue admission,
  and AE supervisor persistence remain outside AG.
- Slice 0569 proves those AG routes against AE PostgreSQL test storage. The
  protected smoke writes AE supervisor result/event evidence through AE APIs,
  reads it back through AG admin projection routes, and verifies cleanup while
  keeping `start_daemon` fake/dry-run and blocked.
- Slice 0570 closes S57 with AG still read-only over AE supervisor evidence.
  The closure verifies the protected PostgreSQL smoke hooks and confirms AG has
  no direct AE daemon process control, JobQueue admission, or persistence write
  authority.
- Slice 0571 starts S58 with AG still read-only for supervised daemon process
  evidence. AG may later observe AE-owned process status and guarded outcomes,
  but it must not start or stop AE subprocesses, enqueue AE retention work, or
  write AE persistence directly.
- Slice 0572 keeps the same AG boundary while AE defines the supervised process
  snapshot contract. AG may later project safe process status and lifecycle
  metadata through AE APIs only; it still cannot start/stop processes, write AE
  persistence, enqueue AE jobs, or receive raw runtime payloads.
- Slice 0573 keeps supervised process persistence AE-owned. AG can later read
  safe process snapshot/event summaries through AE service APIs, but it still
  cannot write those tables or directly control the daemon subprocess.
- Slice 0574 opens the AE supervised process evidence API target. AG remains
  read-only and should consume only safe AE route projections in a later slice;
  direct AE database writes, JobQueue admission, subprocess start/stop, and raw
  daemon runtime payloads remain outside AG.
- Slice 0575 verifies that AE API target with protected PostgreSQL smoke
  evidence. AG still does not connect to AE's database directly; the next AG
  slice should project only the safe AE route response shape.
- Slice 0576 adds that AG read-only projection foundation for supervised
  process snapshot collection/detail evidence. AG summarizes safe process
  status, event, and adapter metadata from AE APIs while redacting raw process
  snapshots, database URLs, storage paths, artifact payloads, execution
  payloads, and daemon runtime payloads.
- Slice 0577 exposes the supervised process projection through protected AG
  admin read-only routes under
  `/admin/v1/operations/artifact-retention/scheduler-daemon-process-snapshots`.
  The routes validate action/status/limit filters and keep AE as the only
  persistence and subprocess-control owner.
- Slice 0578 adds protected PostgreSQL smoke evidence for that AG read model.
  The smoke writes `MISSING` and `RUNNING` supervised process snapshots through
  AE APIs, reads the `RUNNING` evidence through AG admin routes, verifies direct
  `nex_ae_test` row/index/JSONB observations, and cleans up inserted rows.
- Slice 0579 folds the same supervised process read model into the AG artifact
  retention automation dashboard. Operators can see running/stale/failed/blocked
  process counts and process attention state without AG taking ownership of AE
  persistence or subprocess control.
- Slice 0580 closes S58 with a quality-gate checkpoint over supervised process
  activation boundaries, AE persistence/API evidence, AG read-only projections,
  protected PostgreSQL smokes, and the automation dashboard rollup.
- Slice 0581 starts S59 with AG as the operator-facing dispatcher only. AG can
  later request guarded AE operator control, but it remains read-only over AE
  persistence and never directly starts, stops, or restarts AE subprocesses.
- Slice 0582 keeps that AG role unchanged while AE defines the canonical
  operator-control policy/request contract that AG must later submit through AE
  APIs with operator subject, idempotency, reason, and start/restart approval.
- Slice 0583 keeps admission AE-owned. AG may later display the safe admission
  status and request AE to evaluate operator intent, but READY/BLOCKED/NOOP
  decisions and supervisor action previews remain AE API outputs, not AG
  process-control authority.
- Slice 0584 keeps command preview AE-owned as well. AG can later show safe
  preview metadata, but the supervisor command envelopes are generated by AE and
  remain preview-only until a protected AE execution Slice explicitly invokes an
  adapter.
- Slice 0585 gives AG a protected AE API target for operator-control policy and
  preview-facade reads. AG may submit operator intent through AE and display the
  safe facade result, but it still cannot dispatch supervisor commands, write AE
  persistence, enqueue AE jobs, or start/stop AE subprocesses directly.
- Slice 0586 adds AE-side PostgreSQL smoke evidence for that facade. The smoke
  proves AG-style requests can reach AE's protected policy/preview routes
  against `NEX_AE_TEST_DATABASE_URL` while remaining preview-only and leaving
  AE supervised-process persistence unchanged.
- Slice 0587 projects that AE-owned operator-control policy/preview facade into
  AG as read-only metadata. AG can validate operator intent, call AE policy and
  preview APIs, and summarize READY/BLOCKED/NOOP status, but it still cannot
  dispatch supervisor commands, write AE persistence, enqueue AE jobs, or signal
  AE subprocesses directly.
- Slice 0588 folds the same operator-control status-probe into the AG artifact
  retention automation dashboard. Operators can now see policy/facade loaded
  state, action/status, preview count, restart support, and preview-only
  guardrails beside batch, scheduled job, history, daemon, and supervised
  process rollups; source failures degrade the dashboard without giving AG
  process ownership.
- Slice 0589 adds protected AG-to-AE PostgreSQL smoke evidence for the
  operator-control surface. The smoke runs AG's admin policy/status-probe/restart
  preview routes against an AE service app backed by `NEX_AE_TEST_DATABASE_URL`,
  verifies AE bridge status, and proves preview calls do not mutate AE
  supervised-process persistence.
- Slice 0590 closes S59 by checking the full guarded operator-control path:
  boundary audit, AE contracts/facade, AE and AG-to-AE protected smoke, AG
  read-only projections, automation dashboard rollup, redaction posture, and
  preview-only restart stop-then-start evidence.
- Slice 0591 starts S60 while keeping AG as dispatcher/projection only. AG may
  later submit execution intent through AE, but AE remains the only service that
  invokes supervisor adapters or writes supervisor execution evidence.
- Slice 0592 keeps that boundary while AE defines the canonical execution
  request/result contract. AG should treat execution evidence as AE-owned
  metadata, submit intent through AE APIs in later slices, and never directly
  invoke adapters, write AE persistence, enqueue AE jobs, or signal AE
  subprocesses.
- Slice 0593 keeps AG in that same dispatcher/projection role while AE adds
  the execution state machine and idempotency contract. AG may later display
  safe ADMITTED/BLOCKED/NOOP/REPLAYED/CONFLICT evidence, but transitions remain
  AE-owned and metadata-only until a protected AE execution route is added.
- Slice 0594 gives AG a protected AE API target for execution state and
  transition evidence, but AG remains a caller/projection surface only. AE still
  builds the facade, execution request, state, and transition contracts and does
  not permit AG to invoke adapters or mutate AE persistence directly.
- Slice 0595 keeps AG out of AE persistence while adding an AE-side PostgreSQL
  smoke for the protected execution route. Later AG slices can use this evidence
  as the dispatcher baseline before adding AG projections or dashboards.
- Slice 0596 gives AG a future AE API read target for operator-control
  execution evidence. AE owns the persisted execution states and transitions;
  AG should consume the protected collection/detail routes as read-only
  projection data and still must not write AE tables or control AE processes
  directly.
- Slice 0597 adds AG projection builders and AE client methods for
  operator-control execution collection/detail read models while excluding raw
  execution requests, nested transition state payloads, and idempotency keys.
- Slice 0598 exposes those projections through protected AG admin routes for
  operator-control execution collection/detail evidence. The routes validate
  service, action, execution status, idempotency status, and limit filters, then
  call AE APIs as read-only sources.
- Slice 0599 proves the AG routes against an AE service app backed by
  `NEX_AE_TEST_DATABASE_URL`. The protected smoke writes one explicit fake
  dry-run execution state and transition, reads them through AG, and cleans up
  the targeted test rows with `states=1`, `transitions=1`, `cleanup_states=1`,
  `cleanup_transitions=1`, and `live_db=true` evidence.
- Slice 0600 closes S60 with AG still acting only as a read-only operator
  projection/admin route surface over AE-owned execution persistence.
- Slice 0601 starts S61 with AG still outside worker execution ownership. AG may
  project AE worker state and expose operator diagnostics later, but it must
  keep using AE APIs and must not write AE execution tables, enqueue AE worker
  work, or start/stop AE subprocesses directly.
- Slice 0602 keeps that boundary while AE defines worker plan/command
  contracts. AG should treat these as future AE-owned read-model inputs only;
  it still must not construct worker commands, dispatch supervisor adapters, or
  write AE execution state directly.
- Slice 0603 adds an AE-owned worker transition-plan contract. AG may later
  project its safe summaries, but it must continue to read through AE APIs and
  must not persist transition rows or infer alternate worker state paths.
- Slice 0604 keeps worker execution AE-owned while adding a fake dry-run worker
  result contract. AG may later read projected worker summaries only; it still
  must not invoke worker adapters, supervisor adapters, subprocess control, or
  AE persistence directly.
- Slice 0605 gives AG a future AE API target for worker-result diagnostics, but
  execution remains AE-owned. AG should call AE's protected worker route as a
  client/projection surface only and must not write AE execution state,
  transition, or worker evidence tables directly.
- Slice 0606 proves the AE-owned worker route against the real AE test DB. AG
  can rely on the evidence that AE persists and cleans up execution
  state/transition rows itself while worker execution remains fake dry-run and
  non-persistent.
- Slice 0607 adds an AG worker execution projection foundation. AG can now call
  the AE worker result route through its source client and publish a redacted
  worker summary, but worker execution, transition persistence, subprocess
  control, and JobQueue ownership remain inside AE.
- Slice 0608 exposes that worker projection through a protected AG admin route
  for the operations dashboard. The route validates service scope and execution
  state identity, delegates to AE, and returns only the redacted worker
  projection.
- Slice 0609 proves the AG worker projection route against the real AE test DB
  when explicitly enabled. The smoke persists one AE execution state, has AG
  call AE's protected worker route, verifies the redacted worker projection, and
  cleans up the targeted row while leaving AG read/projection-only.
- Slice 0610 closes S61 with AG still acting only as a protected read-only
  operator projection over AE-owned worker execution. The checkpoint keeps AG
  outside AE database writes, JobQueue enqueue, worker-result persistence, real
  process control, and physical deletion automation.
- Slice 0611 starts S62 with worker result persistence still AE-owned. AG may
  later expose read-only result projections over AE APIs, but must not persist
  `ae_op_exec_worker_results`, enqueue AE work, store raw worker payloads, or
  control AE processes directly.
- Slice 0612 adds the AE-owned worker result table/store foundation only on the
  AE side. AG must continue to consume future result evidence through AE APIs
  and must not write `ae_op_exec_worker_results` or store raw worker result
  payloads.
- Slice 0613 makes AE worker-result persistence an explicit AE route concern.
  AG may later project those persisted records through protected AE read APIs,
  but it must not set itself up as the writer for `ae_op_exec_worker_results`.
- Slice 0614 adds protected AE-side PostgreSQL smoke evidence for persisted
  worker results. AG can rely on that evidence later, but it still remains a
  read-only projection client and must not access or mutate the AE worker result
  table directly.
- Slice 0615 gives AG a future protected AE read-model target for persisted
  worker results. AG should consume the AE list/detail APIs as a projection
  source only and continue to avoid direct access to `ae_op_exec_worker_results`.
- Slice 0616 adds the AG projection/client foundation for persisted worker
  results. AG now understands AE worker-result collection/detail read-model
  shapes, summarizes safe status/hash evidence, and still avoids direct AE
  database access, JobQueue enqueue, supervisor dispatch, and daemon process
  control.
- Slice 0617 exposes that worker-result projection through protected AG admin
  collection/detail routes and extends the artifact-retention operations smoke
  so dashboard evidence includes worker-result visibility. AG still delegates
  all source reads to AE APIs and does not touch `ae_op_exec_worker_results`
  directly.
- Slice 0618 proves the AG-to-AE worker-result read-model path against the real
  AE test database. The smoke writes one AE execution state and one persisted
  worker result, verifies AE collection/detail reads, verifies AG
  collection/detail projections over the AE APIs, and cleans up targeted rows.
  AG still does not connect to or mutate `ae_op_exec_worker_results` directly.
- Slice 0619 adds a protected AG diagnostics rollup route for AE-persisted
  worker results. The rollup classifies `NO_RESULTS`, `READY`, and `ATTENTION`
  states from AE collection read-model data and reports only safe counts,
  hash-presence flags, metadata guardrail checks, status-path checks, and
  recommended operator actions.
- Slice 0620 closes S62 with AG still read-only over AE worker-result evidence.
  The checkpoint verifies the AG collection/detail projections, diagnostics
  rollup, PostgreSQL smoke hooks, and redaction posture while keeping AG outside
  AE database writes, JobQueue enqueue, raw worker payload storage, subprocess
  control, and physical deletion automation.
- Slice 0621 starts S63 by freezing AG's owned write boundary for operator
  review notes and redacted evidence exports. Generic note/export persistence
  should use short AG-owned tables such as `ag_op_notes` and `ag_ev_exports`,
  split target refs into indexable columns, store free text as hashes plus short
  previews, and keep AE/CX/MO/OA source records read-only through service APIs.
- Slice 0622 adds the AG-owned operator review note persistence foundation.
  Notes are stored in `ag_op_notes` with indexable target, trace, operator, and
  status columns; free-text note bodies are reduced to SHA-256 hashes plus
  bounded previews, and raw note text remains outside the database contract.
- Slice 0623 adds the operator review note service facade. Mutations require an
  idempotency key, derive stable AG-owned note ids from a hash of that key,
  return `NEW` or `REPLAYED` outcomes, reject conflicting reuse, and never
  persist the raw idempotency key.
- Slice 0624 wires the protected operator review note routes at
  `/admin/v1/operator-review/notes`. The routes accept service-token calls or
  admin user-token calls, require `Idempotency-Key` for mutations, emit
  redacted AG audit events only for new notes, and keep replay responses
  side-effect free.
- Slice 0625 adds
  `scripts/smoke/run_ag_operator_review_note_postgres_smoke.py`, a guarded
  `nex_ag_test` evidence path that runs AG migrations, drives the protected
  note create/replay/list/detail routes, verifies `ag_op_notes` directly in
  PostgreSQL, and cleans up the smoke row.
- Slice 0626 adds the redacted evidence export persistence foundation.
  Export records use the short AG-owned `ag_ev_exports` table, keep target and
  operator refs indexable, and store only manifest metadata plus SHA-256 hashes.
  Raw evidence bodies, prompts, source text, storage paths, and idempotency keys
  remain outside the persisted contract.
- Slice 0627 adds the redacted evidence export service facade. Export mutations
  require `Idempotency-Key`, return `NEW` or `REPLAYED`, reject conflicting key
  reuse, and ignore caller-supplied `export_id` so AG remains the id authority.
- Slice 0628 wires the protected export routes at
  `/admin/v1/operator-review/evidence-exports`. The routes share the S63
  service-token/admin-user authorization boundary, emit one redacted operational
  event only for `NEW` exports, and keep replay responses side-effect free.
- Slice 0629 adds
  `scripts/smoke/run_ag_redacted_evidence_export_postgres_smoke.py`, a guarded
  `nex_ag_test` evidence path that runs AG migrations, drives the protected
  export create/replay/list/detail routes, verifies `ag_ev_exports` directly in
  PostgreSQL, and cleans up the smoke row.
- Slice 0630 closes S63 with
  `scripts/smoke/run_s63_operator_review_evidence_closure.py`. The closure
  checks required note/export files, short table names, protected PostgreSQL
  smoke hooks, redaction posture, Slice 0621-0630 docs, and the quality-gate
  hook for the S63 checkpoint.
- Slice 0631 starts S64 with
  `scripts/smoke/run_ag_operator_review_workbench_boundary_audit.py`. The
  checkpoint keeps the workbench projection AG-owned, adds no table, reuses
  `ag_op_notes` and `ag_ev_exports`, requires read-model-first dashboard
  wiring, and keeps raw notes, evidence bodies, prompts, source text, storage
  paths, service tokens, provider keys, and idempotency keys out of workbench
  evidence.
- Slice 0632 adds the read-only operator review workbench read model at
  `/admin/v1/operator-review/workbench`. The projection groups existing
  AG-owned note/export records by target reference, returns only hash/preview
  note refs and redacted export metadata, and adds no new database table.
- Slice 0633 adds the workbench rollup route at
  `/admin/v1/operator-review/workbench/rollups`. It derives safe target, note,
  export, evidence-item, and attention counts from the read model without
  adding persistence or exposing raw note/evidence payloads.
- Slice 0634 wires the operator review workbench rollup into
  `/admin/v1/operations/dashboard` as the
  `ag_operator_review_workbench_dashboard_section.v1` section. The dashboard
  interprets `service_id` as a workbench target-service filter, reports AG-owned
  source health under `nex-ag`, and keeps workbench access read-only.
- Slice 0635 correlates operator review workbench attention with
  `/admin/v1/operations/issue-candidates` through
  `operator_review_attention_required.v1`. Failed evidence exports become
  `ERROR` candidates; active high-urgency or open notes become `WARNING`
  candidates with safe target refs, runbook ids, and operator actions.
- Slice 0636 hardens operator review workbench search filters. The workbench
  and rollup routes now accept `note_status`, `export_status`, `updated_from`,
  and `updated_to` alongside target, trace, operator, and limit filters, and the
  AG note/export stores apply those filters before limiting records.
- Slice 0637 freezes the operator review workbench contract surface with
  dedicated JSON Schemas, positive and negative contract fixtures, and OpenAPI
  paths for `/admin/v1/operator-review/workbench` and
  `/admin/v1/operator-review/workbench/rollups`.
- Slice 0638 adds
  `scripts/smoke/run_ag_operator_review_workbench_postgres_smoke.py`, a guarded
  `nex_ag_test` evidence path that runs AG migrations, writes one note and one
  redacted evidence export, reads workbench/rollup/dashboard/issue-candidate
  projections through protected routes, verifies `ag_op_notes` and
  `ag_ev_exports` directly in PostgreSQL, and cleans up both smoke rows.
- Slice 0639 adds
  `scripts/smoke/run_ag_operator_review_workbench_privacy_regression.py`, a
  mock-first leak regression that intentionally injects unsafe raw fields into
  note/export records, drives workbench/rollup/dashboard/issue-candidate
  routes, and verifies only bounded note previews, hashes, safe target refs,
  and redaction flags leave the AG workbench boundary.
- Slice 0640 closes S64 with
  `scripts/smoke/run_s64_operator_review_workbench_closure.py`. The closure
  checks required workbench files, Slice 0631-0640 docs, contract/OpenAPI
  artifacts, default quality-gate hooks, the protected PostgreSQL smoke path,
  the privacy regression pack, short source table names, and the AG-owned
  workbench projection boundary.
- Slice 0641 starts S65 by freezing the AG-owned operator review case/action
  boundary before adding case persistence or action routes. Cases should use a
  short AG-owned table name such as `ag_op_cases`, actions should first be
  modeled as idempotent state transitions plus AG operational events, and
  source AE/CX/MO/OA records remain read-only through service APIs. Notification
  delivery and external incident sync are deferred until the case loop is
  stable.
- Slice 0642 adds the `ag_op_cases` persistence foundation. The store supports
  in-memory and SQLAlchemy-backed regression paths, keeps target and assignee
  fields indexable, stores resolution text as hash plus bounded preview only,
  and preserves the operational-event-first action history policy.
- Slice 0643 wires case persistence into protected AG admin routes at
  `/admin/v1/operator-review/cases`. The service supports idempotent create,
  list, and detail reads, emits redaction-safe operational events for new cases,
  and keeps explicit action command state transitions deferred to later S65
  slices.
- Slice 0644 adds the internal operator review case action state machine. AG can
  now validate and apply acknowledge, assign, resolve, dismiss, and reopen
  transitions with idempotent replay/conflict handling while keeping action
  history operational-event-first and comments stored as hashes plus bounded
  previews only.
- Slice 0645 exposes the state machine at
  `POST /admin/v1/operator-review/cases/{case_id}/actions`. The route reuses AG
  operator-review auth, requires an `Idempotency-Key`, returns 201 for new
  actions and 200 for replay, and emits a redaction-safe operational event only
  for new actions.
- Slice 0646 adds `GET /admin/v1/operator-review/cases/rollups`, a protected
  case/action rollup for dashboard correlation. It reuses case filters,
  summarizes case status/priority/assignment/latest-action attention, and keeps
  comments, idempotency keys, prompts, storage paths, and raw provider/source
  material out of the payload.
- Slice 0647 wires that case/action rollup into
  `/admin/v1/operations/dashboard` as `operator_review_cases`. The section
  reports safe case counts, status/priority/action buckets, attention items,
  source status, and degraded-source evidence while preserving the hash/preview
  and operational-event-first action-history boundaries.
- Slice 0648 freezes the operator review case/action contract surface with
  dedicated JSON Schemas, positive and negative contract fixtures, and OpenAPI
  paths for `/admin/v1/operator-review/cases`,
  `/admin/v1/operator-review/cases/rollups`,
  `/admin/v1/operator-review/cases/{case_id}`, and
  `/admin/v1/operator-review/cases/{case_id}/actions`.
- Slice 0649 adds
  `scripts/smoke/run_ag_operator_review_case_postgres_smoke.py`, a guarded
  `nex_ag_test` smoke path that runs AG migrations, creates an operator review
  case, replays the idempotent create, applies an assignment action, reads
  detail/list/rollup/dashboard projections, verifies `ag_op_cases` directly in
  PostgreSQL, and cleans up the smoke row.
- Slice 0650 closes S65 with
  `scripts/smoke/run_s65_operator_review_case_action_closure.py`. The closure
  checks required case/action files, Slice 0641-0650 docs, `ag_op_cases`, the
  operational-events-first action history policy, contract/OpenAPI artifacts,
  the protected PostgreSQL smoke path, and redaction-safe documentation.
- Slice 0651 starts S66 with
  `scripts/smoke/run_ag_operator_review_case_workbench_boundary_audit.py`. The
  checkpoint keeps the case workbench AG-owned and read-model-first, adds no new
  table, reuses `ag_op_cases` for the queue and `service_operational_events` for
  action timeline evidence, links only safe workbench/note/export refs, and
  keeps raw comments, source text, storage paths, database URLs, tokens, and
  idempotency keys out of case workbench evidence.
- Slice 0652 adds the operator-facing case queue read model at
  `/admin/v1/operator-review/cases/queue`. The queue reuses `ag_op_cases` and
  the existing case filters, returns safe target/operator/assignment refs,
  attention status, recommended actions, latest safe action summaries, and
  detail/action links, and keeps raw comments, raw resolution text, prompts,
  source text, storage paths, and idempotency keys out of the payload.
- Slice 0653 hardens that case queue with queue-specific
  `latest_action_type`, `attention_status`, `q`, `sort_by`, and
  `sort_direction` controls. The projection returns normalized filter/sort
  metadata, searches only safe queue fields, keeps the default attention-first
  ordering, and adds no new table or migration.
- Slice 0654 adds
  `GET /admin/v1/operator-review/cases/{case_id}/workbench-detail`, a
  metadata-safe detail projection for operator screens. It reuses `ag_op_cases`,
  returns safe refs, attention metadata, latest safe action summary, action
  controls, and resolution hash/preview only, while leaving timeline event
  expansion to a later S66 slice.
- Slice 0655 adds
  `GET /admin/v1/operator-review/cases/{case_id}/timeline`. The route reads AG
  operational events for case creation and case actions, returns only
  metadata-safe event refs and hash fields, and reports safe
  `timeline_status=UNAVAILABLE` source errors instead of adding a case action
  history table.
- Slice 0656 extends `/admin/v1/operations/dashboard` and
  `/admin/v1/operations/issue-candidates` with case workbench signals. The
  dashboard now exposes queue/detail/timeline entrypoints and a safe queue
  summary, while issue candidates add
  `operator_review_case_attention_required.v1` for case lifecycle attention
  separately from workbench target attention.
- Slice 0657 freezes the case workbench contract surface with
  `operator_review_case_workbench.v1.schema.json`, positive fixtures for queue,
  detail, and timeline, negative raw-comment leak fixtures, and OpenAPI paths
  for `/admin/v1/operator-review/cases/queue`,
  `/admin/v1/operator-review/cases/{case_id}/workbench-detail`, and
  `/admin/v1/operator-review/cases/{case_id}/timeline`.
- Slice 0658 adds
  `scripts/smoke/run_ag_operator_review_case_workbench_postgres_smoke.py`, a
  guarded `nex_ag_test` smoke path that runs AG migrations, creates a case,
  applies an assignment action, reads queue/detail/timeline projections, verifies
  `ag_op_cases` and `service_operational_events` directly in PostgreSQL, and
  cleans up the smoke case and timeline events.
- Slice 0659 adds
  `scripts/smoke/run_ag_operator_review_case_workbench_privacy_regression.py`, a
  mock-first leak regression that injects unsafe raw action comments, prompts,
  source text, storage paths, provider keys, tokens, database URLs, and
  idempotency keys into case records/events, then verifies queue, detail,
  timeline, dashboard, and issue-candidate surfaces expose only safe hashes,
  refs, redaction flags, and operational-event metadata.
- Slice 0660 closes S66 with
  `scripts/smoke/run_s66_operator_review_case_workbench_closure.py`. The
  checkpoint verifies Slice 0651-0660 docs, queue/detail/timeline runtime
  hooks, `ag_op_cases` plus `service_operational_events` as the S66 source
  tables, contract/OpenAPI artifacts, protected PostgreSQL smoke coverage,
  privacy regression coverage, and redaction-safe documentation for the
  `ag_owned_operator_review_case_workbench_projection` boundary.
- Slice 0661 starts S67 with
  `scripts/smoke/run_ag_operator_review_case_evidence_admission_boundary_audit.py`.
  The checkpoint keeps evidence/admission AG-owned, adds no new table, reuses
  `ag_op_cases`, `ag_op_notes`, `ag_ev_exports`, and
  `service_operational_events`, treats action-admission as preflight-only, and
  keeps raw notes, evidence bodies, action comments, prompts, source text,
  storage paths, provider payloads, database URLs, tokens, and idempotency keys
  out of evidence/admission payloads.
- Slice 0662 adds the case evidence-link read model foundation. It reuses the
  case target ref to gather matching operator notes and redacted evidence
  exports, returns only safe refs, hashes, bounded previews, counts, status
  fields, timestamps, and detail paths, and leaves the protected route wiring to
  Slice 0663.
- Slice 0663 exposes that read model at
  `GET /admin/v1/operator-review/cases/{case_id}/evidence-links`. The route
  uses the existing AG operator-review authorization boundary, target-scoped
  note/export stores, and the shared bounded `limit` query option while keeping
  raw notes, raw evidence bodies, storage refs, provider payloads, database
  URLs, tokens, and idempotency keys out of the response.
- Slice 0664 adds the action-admission decision model. It derives admitted and
  blocked actions from the same case action state machine used by mutations,
  marks the projection as preflight-only, points back to the authoritative
  `POST /admin/v1/operator-review/cases/{case_id}/actions` mutation route, and
  keeps raw comments, prompts, metadata payloads, storage refs, provider
  payloads, database URLs, tokens, and idempotency keys out of the payload.
- Slice 0665 exposes that model at
  `GET /admin/v1/operator-review/cases/{case_id}/action-admission`. The route
  supports an optional `action_type` query parameter, remains protected by the
  AG operator-review authorization boundary, returns standard case-not-found
  and unsupported-action problems, and remains preflight-only.
- Slice 0666 integrates the evidence/admission surfaces into
  `GET /admin/v1/operator-review/cases/{case_id}/workbench-detail` as
  lightweight summaries and route links. The detail surface reports evidence
  source status (`READY`, `PARTIAL`, or `NOT_CONFIGURED`), does not inline
  evidence items or admission decision items, and keeps the existing evidence
  and mutation routes authoritative.
- Slice 0667 freezes the evidence/admission contract surface in
  `contracts/schemas/service/nex_ag/operator_review_case_workbench.v1.schema.json`,
  adds positive examples for the evidence-link and action-admission route
  payloads, updates the workbench-detail example, and documents both protected
  S67 routes in the AG OpenAPI file.
- Slice 0668 adds the protected PostgreSQL smoke evidence in
  `scripts/smoke/run_ag_operator_review_case_evidence_admission_postgres_smoke.py`.
  The opt-in smoke runs AG migrations against `NEX_AG_TEST_DATABASE_URL`, writes
  a case, matching operator note, and redacted evidence export into
  `ag_op_cases`, `ag_op_notes`, and `ag_ev_exports`, then verifies
  workbench-detail, evidence-link, and action-admission routes without exposing
  raw notes, raw evidence bodies, database URLs, or idempotency keys.
- Slice 0669 adds the deterministic privacy regression in
  `scripts/smoke/run_ag_operator_review_case_evidence_admission_privacy_regression.py`.
  The unsafe in-memory fixture injects raw notes, raw evidence bodies, comments,
  prompts, storage paths, provider payloads, database URLs, tokens, and
  idempotency keys into case/note/export records, then asserts S67 public
  payloads expose only safe refs, hashes, bounded previews, summary counts,
  state-machine admission metadata, redaction flags, and route links.
- Slice 0670 closes S67 with
  `scripts/smoke/run_s67_operator_review_case_evidence_admission_closure.py`.
  The checkpoint verifies Slice 0661-0670 docs, quality-gate hooks,
  `ag_op_cases`/`ag_op_notes`/`ag_ev_exports` source tables, evidence-link and
  action-admission contracts/OpenAPI entries, protected PostgreSQL smoke
  coverage, privacy regression coverage, and redaction-safe documentation for
  the `ag_owned_operator_review_case_evidence_admission` boundary.
- Slice 0671 starts S68 with
  `scripts/smoke/run_ag_operator_review_case_decision_lifecycle_boundary_audit.py`.
  The checkpoint keeps the decision lifecycle AG-owned, adds no new table,
  reuses `ag_op_cases`, `service_operational_events`, `ag_op_notes`, and
  `ag_ev_exports`, keeps action history operational-events-first, and defers
  closure packet persistence until query or retention requirements prove a
  dedicated table is necessary.
- Slice 0672 hardens
  `GET /admin/v1/operator-review/cases/{case_id}/timeline` as the first S68
  lifecycle read-model step. Timeline items now carry deterministic sequence
  numbers, `timeline_kind`, safe `action_outcome` transition facts, and
  item-level redaction flags while continuing to read `service_operational_events`
  and exclude raw comments, resolution text, event details, idempotency keys,
  metadata payloads, provider payloads, storage paths, database URLs, and tokens.
- Slice 0673 adds `ag_operator_review_case_action_outcomes.v1` as an internal
  lifecycle read model derived from the hardened timeline. It summarizes safe
  status transition, assignment, terminal, and resolution-recorded action facts
  while preserving timeline sequence correlation and keeping action history
  `operational_events_first`.
- Slice 0674 adds `ag_operator_review_case_assignment_workload.v1` as an
  internal read model over the case list. It groups assigned and unassigned case
  workload, status, priority, attention, latest-action, and recommended-action
  counts without creating a new table or exposing raw operator text.
- Slice 0675 adds `ag_operator_review_case_closure_packet.v1` as a read-model
  closure packet foundation. The packet combines safe case refs, resolution
  hash, timeline summary, action outcome facts, and evidence-link refs from
  existing sources, marks closure readiness, excludes resolution previews, and
  remains non-persistent.
- Slice 0676 exposes the closure packet through protected
  `GET /admin/v1/operator-review/cases/{case_id}/closure-packet` with bounded
  evidence/timeline query controls. The route is read-only, AG-owned, and keeps
  the packet non-persistent.
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
