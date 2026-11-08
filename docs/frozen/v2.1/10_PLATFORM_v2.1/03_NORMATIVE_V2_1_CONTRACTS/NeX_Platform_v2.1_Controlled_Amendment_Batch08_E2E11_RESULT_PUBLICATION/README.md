# NeX Platform v2.1 E2E Step 5 Result Publication Hardening v1.6

This Controlled Amendment closes E2E-11 Result Publication Failure gaps without changing Frozen Agent v2.1 or Frozen NSL v0.2 semantics.

Canonical rules:

- AE Runtime owns immutable AgentResult and per-target ResultDelivery operational state.
- BusinessOperationId != PublicationOperationId.
- AgentResult / ResultDelivery / NotificationView are distinct objects and state machines.
- Required deliveries are Workspace durable result, WC WorkResult, and explicitly required Artifact according to source/work contract.
- Notification / Email / Messenger / WA / metrics / analytics / dashboard fan-out are optional asynchronous deliveries and cannot block AgentExecution SUCCEEDED.
- Every publication attempt performs AS_OF_NOW OA/scope/classification/visibility preflight.
- UNKNOWN_DELIVERY uses publication-specific reconciliation; it never re-enters Business WRITE.
- Same AgentResult + target preserves stable PublicationOperationId and publication idempotency identity across retry/reconciliation.
- AgentExecution may enter SUCCEEDED only after AgentResult is durable and every required ResultDelivery is ACKNOWLEDGED.

Machine-readable contracts are in `AE_PUBLICATION/`.
