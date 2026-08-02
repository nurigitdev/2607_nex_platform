# nex-ag

Slice 0001 shell for NeX Admin and Governance.

Owned database env: `NEX_AG_DATABASE_URL`.

Current endpoints:

- `GET /health`
- `GET /ready`
- `GET /version`
- `GET /internal/v1/auth/service-claim`
- `GET /admin/v1/readiness/services`
- `GET /admin/v1/generation-audit/generations/{cx_generation_id}`

Generation audit:

- AG assembles read-only generation audit projections through CX and AE service
  APIs. The projection includes safe generation summaries, progress timeline
  events, optional artifact handoff summaries, and an
  `ag_generation_audit_event.v1` event without raw prompts, provider paths,
  source text, generated output text, or storage paths.
