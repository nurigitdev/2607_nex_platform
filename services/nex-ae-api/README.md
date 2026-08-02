# nex-ae-api

Slice 0001 shell for NeX Agent Experience API.

Owned database env: `NEX_AE_DATABASE_URL`.

Current endpoints:

- `GET /health`
- `GET /ready`
- `GET /version`
- `GET /internal/v1/auth/service-claim`
- `POST /api/v1/chat/interactions`
- `GET /api/v1/chat/interactions/{interaction_id}`
- `POST /api/v1/retrieval/contexts`
- `GET /api/v1/retrieval/contexts/{retrieval_interaction_id}`
- `GET /api/v1/prompts/bindings`
- `GET /api/v1/prompts/render-events/{prompt_render_event_id}`

Prompt registry seed:

- `ae.grounded_chat.default` records the grounded chat system prompt for debug
  and later prompt analytics lineage.

Chat interactions can include a `retrieval` object. When enabled, AE asks CX for
a retrieval context package first, injects cited evidence into the CX generation
request, records a compact retrieval summary, and returns `NO_ANSWER` without
calling generation when CX has no supporting evidence.
