# Service Boundary

Status: Draft bootstrap.

This document defines the first NeX-Platform service boundaries. The names are
stable enough to use in SRS and architecture drafts, but the internal module
layout of each service remains open until implementation planning.

See [Service Boundary Decision Record](../../12_service_boundary_decision_record.md)
for the Slice 422 ownership freeze candidate, source conflicts, and canonical
call chains.

## Boundary Matrix

| Service | Owns | Does Not Own | Primary Consumers |
| --- | --- | --- | --- |
| `nex-cx` | Source document repository, original files, extraction artifacts, normalized Markdown, chunk records, chunk adjacency, embedding vectors, BM25 keyword index, graph metadata, retrieval APIs, provider-facing document-grounded generation records. | User-facing chat UX, model runtime lifecycle, platform-wide auth, admin governance UI. | `nex-ae-api`, `nex-ag`, `nex-mo`. |
| `nex-ae-web` | User UI/UX for chat, search compare, generation, summaries, report artifacts, downloads, previews, Korean default and English support. | Retrieval storage, provider hosting, auth authority, governance policies. | End users and administrators using the workspace. |
| `nex-ae-api` | Agent orchestration, prompt intent detection, search and generation requests to `nex-cx`, generation policy package, answer packaging, citation formatting, artifact creation coordination. | Raw vector storage, provider deployment, identity issuing, global policy ownership, direct document-generation calls to `nex-mo`. | `nex-ae-web`, `nex-cx`, `nex-oa`. |
| `nex-mo` | Embedding provider, reranker provider, generation provider registration, provider route health, runtime metrics, readiness snapshots, vLLM metrics, provider resource monitoring. | User sessions, source document ownership, business document templates, enterprise auth claims, document-grounded generation orchestration. | `nex-cx`, `nex-ag`, operations users. |
| `nex-oa` | NeX Open Auth, user authentication, service-to-service authentication, token/session/API key lifecycle, permission claims, trust boundary enforcement. | Document retrieval ranking, model serving, UI-specific navigation, platform metrics visualization. | All services. |
| `nex-ag` | Admin & governance, operations dashboard, logs, policy settings, audit trails, readiness checks, data retention controls, monitoring views. | End-user authoring UX, core retrieval storage, model inference execution, identity issuance. | Administrators, operators, governance users. |

## Shared Concepts

| Concept | Canonical Owner | Notes |
| --- | --- | --- |
| User identity | `nex-oa` | Other services consume signed claims and authorization decisions. |
| Document ownership and visibility metadata | `nex-cx` | Must preserve who uploaded what, when, and with what visibility scope. |
| Retrieval package | `nex-cx` produces, `nex-ae-api` consumes | Includes chunks, source anchors, scores, policies, and no-answer signals. |
| Generation policy package | `nex-ae-api` | Combines user intent, template, retrieval package reference, output contract, and user-facing prompt policy. |
| Provider-facing prompt package | `nex-cx` | Combines evidence, template metadata, citation rules, and output schema before calling `nex-mo`. |
| Provider route | `nex-mo` | Includes provider id, model, URL, port, profile, health, and runtime metadata. |
| Audit event | `nex-ag` collects, all services emit | Must include actor, action, target, timestamp, result, and correlation id. |

## Frozen Ownership Summary

| Boundary | Decision |
| --- | --- |
| Auth authority | `nex-oa` owns identity, sessions, tokens, service accounts, service tokens, signing keys, and permission claims. |
| Content authority | `nex-cx` owns original assets, extracted artifacts, normalized text, chunks, BM25, vectors, graph extension points, retrieval, and evidence packages. |
| User orchestration | `nex-ae-api` owns intent, execution mode, prompt/template composition, final answer formatting, and generated artifact metadata. |
| Provider execution | `nex-mo` owns provider aliases, runtime contracts, provider health, model metrics, and resource telemetry. |
| Governance | `nex-ag` observes and governs through service APIs; it does not own identity issuing, corpus data, or provider inference. |

## Integration Style

- Services communicate through explicit APIs, not shared database ownership.
- `nex-cx` exposes retrieval, source context, and document-grounded generation
  APIs to `nex-ae-api`.
- `nex-cx` calls `nex-mo` stable APIs for embedding, reranking, and
  document-grounded generation provider execution.
- Direct `nex-ae-api` to `nex-mo` generation is a later policy decision, not
  the MVP default.
- `nex-oa` issues identity and permission claims that every service validates.
- `nex-ag` reads operational data through service APIs or event streams.
- Shared libraries should contain stable contracts only: errors, response envelopes,
  auth claim models, correlation ids, and observability metadata.

## Boundary Risks

| Risk | Guardrail |
| --- | --- |
| `nex-ae-api` slowly becomes a data repository | Keep source files, chunks, embedding, BM25, graph, and retrieval indexes in `nex-cx`. |
| `nex-mo` becomes an admin console | Keep governance policy and operator UX in `nex-ag`; `nex-mo` owns provider operations APIs and telemetry. |
| `nex-oa` is treated as a utility library | Keep token/session/API key issuance and trust boundary decisions in the service. |
| `nex-ag` is confused with an agent runtime | Use `nex-ag` only for admin & governance; agent behavior belongs to `nex-ae-api`. |
