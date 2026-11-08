# P4-S1 Chat Application-Service Refactor

## Goal

Extract one reusable invocation seam for legacy Chat/RAG create, refresh,
cancel, recovery, and retry operations without changing the HTTP contract or
the existing orchestration behavior.

## Decision

`ChatApplicationService` owns the single-invocation guard. A caller may create
an invocation token before canonical wrapper work begins and share that token
with the legacy fallback:

```text
failure before invocation starts
→ one legacy fallback invocation is allowed

callback starts
→ token becomes INVOKING
→ success becomes COMPLETED
→ exception becomes FAILED
→ either terminal state rejects replay
```

The existing route logic remains behavior-compatible and is now reached only
through thin HTTP adapters backed by the injected application service. This is
the seam P4-S4/P4-S6 will reuse for disabled, shadow, and required rollout.

## Scope

- added `nex_ae_api.chat_application`;
- injected the application service through `register_chat_routes`;
- published it as `app.state.ae_chat_application_service`;
- routed create/refresh/cancel/recovery/retry through the common seam;
- retained all existing auth, owner scope, persistence, generation, and error
  behavior;
- added exact-once, pre-invocation fallback, post-invocation replay rejection,
  operation mismatch, and HTTP adapter tests.

No database migration, provider call, Project model, AgentExecution, or rollout
mode is introduced by P4-S1.

## Verification

The Slice Gate owns the AE service regression set and requires statement
coverage >= 95% and branch coverage >= 94% for the new application-service
module.
