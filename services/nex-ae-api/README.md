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
