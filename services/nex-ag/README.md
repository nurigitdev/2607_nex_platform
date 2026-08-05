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
- `GET /admin/v1/operations/events`
- `GET /admin/v1/operations/jobs`
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
- Filters include service id, severity, event type, trace id, and limit.
- Event details are redacted by the shared runtime before AG projection.

Job operations:

- AG exposes a read-only job operations projection over the shared
  `common_job.v1` shape.
- Filters include service id, status, job type, and limit.
- The projection summarizes active/terminal jobs, status counts, service
  counts, job-type counts, and per-service source availability.
- Default runtime registration is mock-first. DB-backed per-service queues can
  be injected later without changing the AG endpoint shape.
