# P4-S3 Conversation 1:N and Append-Only Journal

## Goal

Introduce project-neutral Conversation identity and an owner-scoped,
append-only message/event journal while retaining the mutable v1 Chat
interaction projection.

## Decision

- one Workspace may own multiple `ae_conversations`;
- Conversation has no `project_id` or Project binding;
- `ae_workspaces.chat_document_id` remains the compatibility/default
  Conversation pointer and is not removed;
- `ae_chat_interactions` remains the mutable v1 projection;
- message and event rows share a monotonic Conversation `journal_seq`;
- raw message content is held in owner-private storage while PostgreSQL stores
  only opaque reference, SHA-256, byte size, type, and lineage;
- private content supports memory for tests, a permission-restricted local
  filesystem root, and the existing RustFS-compatible S3 object-store profile;
  an explicitly selected but invalid durable profile fails closed;
- event metadata rejects raw-content keys recursively;
- journal corrections append a row using `supersedes_*`; ordinary update and
  delete are rejected by PostgreSQL triggers.

This journal is not canonical Agent Memory. Weekly digest, compaction,
summarization, Project association, and retrieval injection remain excluded.

## Verification

P4-S3 tests cover Workspace 1:N, default Conversation identity compatibility,
owner isolation, cross-kind ordering, immutable correction lineage, content
integrity, private-storage rollback, forbidden event content, schema shape, and
the absence of Project and digest structures.

Result:

- AE Slice Gate: `2980 passed, 5 skipped`;
- overall coverage: statement `98.34%`, branch `96.24%`;
- `conversation_journal.py`: statement `99.52%`, branch `98.96%`;
- contract validation: 174 schemas, 236 positive examples, 204 negative
  examples, and 7 OpenAPI documents.
