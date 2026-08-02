# NeX-Platform Database Foundations

Status: Slice 0021 persistent schema foundation.

Each service owns its own database and migrations. Cross-service joins and
foreign keys are intentionally avoided; service APIs and contract records carry
references between services.

## Layout

```text
database/
  nex-ae-api/
    migrations/
  nex-cx/
    migrations/
```

## Ownership

| Service | Database Env | Migration Directory |
| --- | --- | --- |
| `nex-ae-api` | `NEX_AE_DATABASE_URL` | `database/nex-ae-api/migrations/` |
| `nex-cx` | `NEX_CX_DATABASE_URL` | `database/nex-cx/migrations/` |

## Slice 0021 Principles

- CX owns content lifecycle persistence: source blobs, logical documents,
  ACL entries, extraction artifacts, chunks, indexes, summaries, summary
  embeddings, and CX prompt registry records.
- AE owns user-facing chat state, prompt analytics, intent classification,
  user task profiles, automation recommendations, feedback, and AE prompt
  registry records.
- Original file dedupe is scoped to active logical documents for a single
  `tenant_id + owner_user_id + source_sha256`; another user may upload the same
  bytes without learning that the file already exists.
- Vector payloads are not stored in these base tables. The foundation records
  model/profile lineage, vector dimensions, hashes, and optional storage URIs so
  a pgvector or external vector store can be added later.
- Raw user prompts are not stored in analytics tables. Analytics keeps hashes,
  short previews, normalized intent, categories, and outcomes.
