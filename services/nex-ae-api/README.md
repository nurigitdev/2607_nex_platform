# nex-ae-api

Slice 0001 shell for NeX Agent Experience API.

Owned database env: `NEX_AE_DATABASE_URL`.

Current endpoints:

- `GET /health`
- `GET /ready`
- `GET /version`
- `GET /internal/v1/auth/service-claim`
- `POST /api/v1/workspaces`
- `GET /api/v1/workspaces/{workspace_id}`
- `GET /api/v1/workspaces/{workspace_id}/activity`
- `POST /api/v1/uploads`
- `GET /api/v1/uploads/{upload_handoff_id}`
- `GET /api/v1/workspaces/{workspace_id}/documents`
- `GET /api/v1/documents/summary-search`
- `POST /api/v1/artifact-handoffs`
- `GET /api/v1/artifact-handoffs/{artifact_handoff_id}`
- `GET /api/v1/compatibility/generation-rules`
- `POST /api/v1/chat/interactions`
- `GET /api/v1/chat/interactions/{interaction_id}`
- `POST /api/v1/retrieval/contexts`
- `GET /api/v1/retrieval/contexts/{retrieval_interaction_id}`
- `GET /api/v1/analytics/prompt-events/{prompt_event_id}`
- `GET /api/v1/analytics/users/{user_id}/task-profile`
- `GET /api/v1/analytics/users/{user_id}/recommendations`
- `GET /api/v1/prompts/bindings`
- `GET /api/v1/prompts/render-events/{prompt_render_event_id}`

Prompt registry seed:

- `ae.grounded_chat.default` records the grounded chat system prompt for debug
  and later prompt analytics lineage.

Workspace state:

- AE owns workspace state, default runtime controls, chat document identity, and
  activity summaries for the user-facing web shell.

Upload handoff:

- AE accepts upload metadata and mock `content_text`, forwards it to CX, and
  stores only safe CX document/job references. Source bytes, storage keys, and
  filesystem paths remain CX-owned.

Document library:

- AE composes workspace document cards from upload handoffs and CX document,
  summary, and summary embedding status. Summary search is lexical and mock-only
  until a persistent AE read model is added.

Artifact handoff:

- AE creates pre-render handoff packages from CX generation and structured
  draft read APIs. Handoffs store safe lineage hashes, target formats,
  validation summaries, actor/workspace refs, and retention policy refs without
  copying raw prompts, source text, provider paths, or local storage paths.

Prompt analytics:

- Chat interactions can record prompt event hashes, short previews, deterministic
  mock intent classifications, user task profiles, and early automation
  recommendation signals without storing full raw prompts.

Chat interactions can include a `retrieval` object. When enabled, AE asks CX for
a retrieval context package first, injects cited evidence into the CX generation
request, records a compact retrieval summary, and returns `NO_ANSWER` without
calling generation when CX has no supporting evidence.
