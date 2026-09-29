# Slice 1071: S107 AE Generated-Response Lineage Closure

## Goal

Close S107 with machine-checkable evidence that generated responses are
durable, owner-scoped, integrity-checked, restart-safe, privacy-safe, and linked
to their chat, CX generation, retrieval, citation, repair, and retry lineage.

## Closure

- CX remains the generation source owner while AE owns the durable user-facing
  response projection and AE Web remains its consumer.
- Response content is stored outside PostgreSQL under private local storage;
  `ae_chat_interactions.generation_summary` stores only validated metadata.
- READY handoffs atomically converge private content and chat lineage with
  replay idempotency and compensation on first-write failure.
- Exact tenant and owner scope protects response reads, while content hash and
  size are revalidated on every load.
- Retry children link parent interactions and parent responses when available;
  bounded citation repair remains final content of the same CX generation.
- Operational events and workspace activity expose bounded metadata without
  content, storage refs, identities, provider details, or lineage identifiers.
- Canonical JSON Schema, positive and negative fixtures, chat contracts, and
  AE OpenAPI `1.5.0` freeze public lineage and exact-owner content surfaces.
- Actual `nex_ae_test` and `nex_cx_test` evidence proves migration currency,
  persistence, restart reads, private mode-`0600` files, owner isolation, and
  zero probe residue.
- The existing `ae_chat_interactions` table is reused; no table was added and
  remote providers remain outside this persistence/lineage boundary.

## Verification

```bash
NEX_AE_GENERATED_RESPONSE_POSTGRES_SMOKE=1 \
NEX_AE_TEST_DATABASE_URL='<AE test database URL>' \
NEX_CX_TEST_DATABASE_URL='<CX test database URL>' \
./.venv/bin/python \
  scripts/smoke/run_s107_ae_generated_response_lineage_closure.py --summary

scripts/quality/run_quality_gate.sh
```

## Observed Evidence

- Protected closure: components `10/10`, gaps `8/8`, PostgreSQL checks `18/18`,
  next `S108`.
- Full Gate: `8539 passed`, `4 skipped` protected PostgreSQL tests.
- Coverage: statement `98.80%`, branch `96.82%`.
- Contracts: schemas `103`, examples `161`, negative examples `124`, OpenAPI
  documents `7`.
- PostgreSQL smoke: AE `nex_ae_test`, CX `nex_cx_test`, checks `18/18`, cleanup
  residue `0/0`.
- Closure target: components `10/10`, gaps `8/8`, PostgreSQL `pass`, next `S108`.
