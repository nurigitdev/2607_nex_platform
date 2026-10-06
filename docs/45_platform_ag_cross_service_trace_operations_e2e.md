# Platform AG Cross-Service Trace, Audit, and Operations E2E

Status: S138 active through Slice 1376.

## Required Outcome

AG must reconstruct one redacted operator timeline for the authenticated golden
journey across OA, AE, CX, and MO. Every source remains service-owned and is
read through an authenticated service API. AG must not read another service's
database or private payload storage.

The timeline covers these ordered stage families:

1. authentication and trust admission;
2. document upload and ownership handoff;
3. durable ingestion and indexing;
4. permission-filtered retrieval and confidence decision;
5. grounded generation, citation validation, and bounded repair;
6. AE generated-response and artifact rendering;
7. preview/download admission and owner denial;
8. failures, recovery, cleanup, and operator evidence.

## Ownership Boundary

- OA owns identity, session, signed-token, and trust audit facts.
- AE owns workspace, upload, generated-response, artifact, and browser-facing
  lifecycle facts.
- CX owns ingestion, retrieval, generation, citation, and private structured
  draft facts.
- MO owns provider route, model/deployment identity, retry, and runtime facts.
- AG owns only redacted projections, correlation, durable operator evidence,
  and operations presentation.

Source APIs expose metadata-safe stage facts only. They never expose prompts,
source text, evidence text, generated text, structured drafts, vectors, bearer
tokens, cookies, credentials, provider URLs, database URLs, storage references,
or absolute paths.

## Access Policy

Cross-service trace source APIs require an OA-issued `nex-ag` service principal
with `service:call` and `operations:read`. The routes use ADMIN admission and
fail closed when either scope, the expected audience, or the caller identity is
missing. Owner identifiers may be represented only by stable opaque digests;
AG must not receive owner-private identifiers merely to reconstruct a trace.

## Integration Gaps

| Gap | Slice | Required closure |
| --- | --- | --- |
| `S138-GAP-01` | `1373` | Define the strict redacted stage-envelope and timeline contracts. |
| `S138-GAP-02` | `1374` | Add CX ADMIN-scoped ingestion/retrieval/generation trace projection. |
| `S138-GAP-03` | `1375` | Add AE upload/response/artifact trace projection. |
| `S138-GAP-04` | `1376` | Add OA trust and MO provider trace projections. |
| `S138-GAP-05` | `1377` | Replace AG compatibility reads with typed service-API clients and aggregation. |
| `S138-GAP-06` | `1378` | Persist redacted AG audit evidence and expose protected operations APIs. |
| `S138-GAP-07` | `1379` | Prove deterministic success, failure, privacy, and restart scenarios. |
| `S138-GAP-08` | `1380` | Prove the service-API-only timeline against actual test PostgreSQL databases. |

Slice 1381 closes contracts and the operator runbook, runs the Full Gate, and
activates S139.

## Existing Foundations

- AG already exposes `GET /admin/v1/operations/traces/{trace_id}`.
- AG generation audit and artifact operations already use authenticated HTTP
  clients, but the CX generation source still targets owner-scoped routes.
- Managed protected profiles already require AG projection mode `api` and
  reject legacy cross-service PostgreSQL mode.
- The S137 journey preserves one trace through retrieval, generation,
  citation/repair, AE response lineage, and artifact rendering.

The four quarantined legacy AG database projection adapters remain available
only to historical unmanaged regression callers until their API replacements
are accepted in S138. They may not be selected by a managed profile.

## Completion Signal

S138 is complete only when AG reconstructs all eight stage families from
authenticated redacted service APIs, persists operator evidence without private
payloads, survives restart, represents partial source failure explicitly,
rejects unauthorized and cross-owner disclosure attempts, and passes actual
test-PostgreSQL plus Full Gate evidence with zero fixture residue.

## Slice 1373 Contract

`cross_service_trace_stage.v1` is the only source-service stage envelope admitted
to the S138 timeline. It allows opaque identifiers, a SHA-256 owner digest,
enumerated lifecycle state, timestamps, and a small allowlist of scalar
operations attributes. Prompt text, source/evidence/generated content, draft
payloads, vectors, credentials, provider URLs, database URLs, storage
references, and file paths are rejected.

`ag_cross_service_trace_e2e.v1` sorts those stages into a single trace timeline,
reports each source API as `READY`, `DEGRADED`, or `UNAVAILABLE`, and becomes
`DEGRADED` when a source is unhealthy or a stage is `FAILED`/`BLOCKED`. Both
contracts explicitly assert `private_payload_included=false`.

## Slice 1374 CX Projection

CX exposes `/internal/v1/operations/traces/{trace_id}` only to an OA-admitted
`nex-ag` service principal carrying `service:call` and `operations:read`; the
route is classified `ADMIN`. It reads existing ingestion, retrieval, and
generation tables through the CX-owned repository boundary. Raw tenant/owner
identifiers and all private content remain inside CX; the response includes
only a stable owner digest, opaque correlation identifiers, lifecycle status,
timestamps, and allowlisted scalar operations metadata.

## Slice 1375 AE Projection

AE exposes the same internal operations path and admission policy for its
upload, generated-response, artifact, and render lifecycle. The projection
reads only existing AE-owned durable tables and returns opaque correlation
identifiers, lifecycle state, progress metadata, timestamps, and a stable
owner digest. Browser messages, generated responses, artifact titles, rendered
files, storage references, and all other private payloads remain inside AE.

## Slice 1376 OA and MO Projections

OA projects authentication and trust events from its existing auth-event and
operational-event stores, replacing user ownership with a stable digest. MO
records provider success/failure into its existing durable operational-event
store and projects model-agnostic capability, alias, model revision,
deployment, route, mode, retryability, result, and opaque request identity.
Both services expose only the AG-only ADMIN route. Provider URLs, credentials,
prompts, outputs, raw telemetry, and user-private identifiers are excluded.

## S139 Handoff

S139 receives the stable trace id, public correlation ids, safe stage status,
and owner-safe browser links needed for Korean-default Playwright acceptance.
It may not consume AG database rows or any service-private audit payload.
