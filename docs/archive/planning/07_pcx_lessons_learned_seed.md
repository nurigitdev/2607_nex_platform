# PCX Lessons Learned Seed

Status: Draft bootstrap.

This file seeds the lessons that should be carried from NeX-PCX into
NeX-Platform design. It is intentionally concise; each item should later be
linked to SRS sections, commits, tests, screenshots, or smoke evidence.

## Content and Retrieval

| Lesson | Platform Impact |
| --- | --- |
| Original files, extracted Markdown/text, source blocks, chunks, and embeddings need separate identities. | `nex-cx` should own durable artifact and chunk source contracts. |
| Chunk adjacency is useful for source context. | Store previous/next chunk links even when overlap is reduced. |
| Chunk policy is an experiment dimension. | Retrieval and embedding records must preserve policy id and freshness. |
| BM25, vector search, hybrid search, and reranking need comparable outputs. | Search APIs should expose score components and ranking stage metadata. |
| No-answer and low-confidence states are necessary. | Retrieval APIs should return guardrail metadata, not just top-k chunks. |

## Provider Operations

| Lesson | Platform Impact |
| --- | --- |
| Embedding, reranker, and vLLM generation providers need health and request smoke evidence. | `nex-mo` should own route registration, readiness, snapshots, and smoke runners. |
| Remote DGX providers can be unavailable during development. | Mock provider mode must remain a first-class path. |
| Runtime dtype and memory footprint matter for Qwen providers. | Provider metadata should include requested dtype, loaded dtype, resident memory, and total memory share. |
| vLLM runtime metrics help operations. | KV cache, throughput, queue, and readiness thresholds belong in `nex-mo` and `nex-ag` surfaces. |

## Generation and Artifacts

| Lesson | Platform Impact |
| --- | --- |
| Search results must be packaged before generation. | `nex-ae-api` should own retrieval context package composition. |
| Citations and source anchors make answers inspectable. | Generation responses should store citation coverage and quality metadata. |
| Templates need prompt-contract alignment. | Active template version and prompt version must be recorded together. |
| Long generation requests need visible progress. | UI should show internal stages: query, retrieval, packaging, provider request, citation check, artifact export. |
| Generated documents need artifact records. | Chat messages should link to artifacts instead of storing all output inline. |

## Auth, Governance, and Operations

| Lesson | Platform Impact |
| --- | --- |
| Upload ownership and query scope change search results. | `nex-oa` claims and `nex-cx` visibility metadata must be designed together. |
| Operators need logs, readiness, queue, and failure drilldowns. | `nex-ag` should be present from the MVP, not postponed indefinitely. |
| Regression coverage can drift near the threshold. | Testing strategy should keep single-pass statement and branch coverage reporting. |
| Startup/shutdown evidence reduces operational ambiguity. | Foreground and service runners should emit PID, log, health, and drain evidence. |

## Candidate Decisions To Validate

- Default generation model: DGX vLLM Qwen3.5-122B-A10B-NVFP4 or later confirmed production model.
- Default embedding profile: Qwen3 embedding 2560 dimension, subject to benchmark confirmation.
- Default chunk policy: start with heading-aware policy, then compare smaller policies only when evidence requires it.
- Default retrieval mode: hybrid with reranking and no-answer guardrail for grounded generation.
