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
- `GET /api/v1/documents/{document_id}`
- `POST /api/v1/artifact-handoffs`
- `GET /api/v1/artifact-handoffs/{artifact_handoff_id}`
- `POST /api/v1/artifacts`
- `GET /api/v1/artifacts/{artifact_id}`
- `GET /api/v1/artifacts/{artifact_id}/versions`
- `POST /api/v1/artifacts/{artifact_id}/render-jobs`
- `GET /api/v1/artifact-render-jobs/{render_job_id}`
- `GET /api/v1/artifact-files/{artifact_file_id}`
- `GET /api/v1/artifact-files/{artifact_file_id}/preview`
- `GET /api/v1/artifact-files/{artifact_file_id}/download`
- `GET /api/v1/compatibility/generation-rules`
- `GET /api/v1/recovery/generation-policies`
- `GET /api/v1/recovery/generation-policies/{failure_code}`
- `POST /api/v1/recovery/generation-requests`
- `GET /api/v1/recovery/generation-requests/{recovery_request_id}`
- `POST /api/v1/chat/interactions`
- `GET /api/v1/chat/interactions/{interaction_id}`
- `POST /api/v1/chat/interactions/{interaction_id}/artifact-links`
- `GET /api/v1/chat/interactions/{interaction_id}/artifact-links`
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
- Slice 0196 adds canonical OA ownership propagation to this existing upload
  facade. AE now forwards `ownership_ref` with `oa.tenant`,
  `owner_subject_ref`, and `uploaded_by_subject_ref` while retaining legacy
  `tenant_id`, `owner_user_id`, and `user_id` aliases for compatibility.
- Slice 0197 completes the CX side of that handoff: CX now canonicalizes the
  propagated `ownership_ref` and rejects mismatched legacy aliases before
  owner-scoped duplicate detection runs.
- Slice 0199 can verify or ensure upload ownership refs with OA before CX is
  called. Set `NEX_AE_UPLOAD_OWNER_RESOLVER_MODE` to `verify` or `ensure` to
  enable the guardrail; the default `disabled` mode preserves mock-first local
  regression behavior.
- Upload handoff records keep the propagated stable subject refs for debugging,
  but do not store passwords, tokens, emails, raw identity profiles, source
  bytes, storage keys, or local filesystem paths.

Document library:

- AE composes workspace document cards from upload handoffs and CX document,
  summary, and summary embedding status. Summary search is lexical and mock-only
  until a persistent AE read model is added.
- AE propagates the upload handoff owner scope (`tenant_id`, `owner_user_id`) as
  CX document detail query parameters before composing document cards. Invalid
  stored owner scope fails in AE with `ae.document_owner_scope_invalid` and does
  not call CX.
- Slice 0211 adds an AE document detail facade. It resolves the document through
  the stored upload handoff, calls the owner-scoped CX detail endpoint once, and
  returns an AE-safe projection that omits source bytes, markdown text, raw
  summaries, embedding vectors, storage keys, storage URIs, and local paths.

Artifact handoff:

- AE creates pre-render handoff packages from CX generation and structured
  draft read APIs. Handoffs store safe lineage hashes, target formats,
  validation summaries, actor/workspace refs, and retention policy refs without
  copying raw prompts, source text, provider paths, or local storage paths.

Artifact records:

- AE creates user-facing artifact shells from validated handoffs. The record
  family fixes source refs, versions, render jobs, files, preview/download
  links, current version, status, and retention metadata while rendering remains
  a later slice.
- AE can synchronously render the first Markdown artifact version from a
  validated CX structured draft. Public artifact records expose version hashes
  and render job metadata, while Markdown content remains private until file and
  preview/download routes are added.
- AE materializes rendered Markdown as safe artifact file metadata with
  `ae://` storage refs and AE-owned preview/download routes. Public metadata
  never exposes local filesystem paths.

Prompt analytics:

- Chat interactions can record prompt event hashes, short previews, deterministic
  mock intent classifications, user task profiles, and early automation
  recommendation signals without storing full raw prompts.

Chat interactions can include a `retrieval` object. When enabled, AE asks CX for
a retrieval context package first, injects cited evidence into the CX generation
request, records a compact retrieval summary, and returns `NO_ANSWER` without
calling generation when CX has no supporting evidence.

Chat artifact links:

- Chat records always include `artifact_refs`. AE can attach a rendered artifact
  ref to the originating interaction when chat document and interaction lineage
  match. The link stores safe artifact/version IDs, preview/download AE routes,
  quality badges, source lineage, and allowed actions without embedding rendered
  content or filesystem paths.

Generation recovery policies:

- AE reads the shared recovery policy catalog for retry, repair, regeneration,
  manual warning acceptance, and artifact render retry decisions. Policies store
  safe owner/action/lineage metadata and redaction-safe hashes only.
- AE can accept a user/operator recovery action for a failed CX generation
  record and store a separate safe recovery request envelope. The request fixes
  policy hash status, next attempt number, dispatch target, and retrieval reuse
  intent without mutating the failed chat or generation record.
