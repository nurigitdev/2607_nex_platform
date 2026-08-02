# Slice 0006 MO Mock Provider Registry

Status: Implemented.

Backlog candidate: `S1-006` MO mock provider alias registry.

Requirement coverage: `MO-FR-001`, `MO-FR-004`.

## Scope

Slice 0006 adds the deterministic MO local-mock provider baseline:

- `services/nex-mo/nex_mo/providers.py`.
- `GET /api/v1/provider-routes`.
- `POST /api/v1/embeddings`.
- `POST /api/v1/rerank`.
- `POST /api/v1/generations`.
- `contracts/schemas/service/nex_mo/provider_route.v1.schema.json`.
- Positive and negative provider route fixtures.

All provider endpoints require a valid OA mock service claim with audience
`nex-mo`.

## Mock Aliases

| Alias | Capability |
| --- | --- |
| `mock-embedding-default` | `embedding` |
| `mock-reranker-default` | `reranking` |
| `general-llm-default` | `generation` |

The mock responses are deterministic, include safe route metadata, and do not
expose provider URLs, model file paths, or secret-bearing runtime details.

## Evidence

Quality gate target:

```text
pytest with statement coverage and branch coverage
coverage threshold check
contract validation with MO provider fixtures
```

## Follow-Up

Slice 0007 should let CX call MO by alias and retain safe request/response
metadata for generation lineage.
