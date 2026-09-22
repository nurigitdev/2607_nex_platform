# Slice 0952: CX Document Intelligence Summary Contract

## Goal

Define deterministic, private-payload-free source, generation-profile,
summary-manifest, and freshness contracts before durable summary storage and
remote generation are wired.

## Implementation

- Adds a source snapshot bound to document, content object, extraction artifact,
  and extracted Markdown SHA-256.
- Adds a generation profile bound to provider alias, model profile/revision,
  deployment, prompt version, and the existing 900/1000 character policy.
- Builds deterministic summary manifest identities from source, generation
  profile, and summary-text hashes without storing summary text in metadata.
- Requires safe relative private-storage keys and rejects absolute or parent
  traversal paths.
- Evaluates freshness fail-closed. Missing manifests, non-READY status, source
  drift, generation-profile drift, malformed hashes, and missing private
  payload references make a summary unusable.
- Provides a public projection that excludes the private storage key, source
  snapshot, and deployment identifier.
- Freezes the current generation model as `Qwen3.5-4B` and the
  future summary embedding model as `Qwen3-Embedding-4B`.

This Slice adds no table, migration, route, provider call, or persistent row.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_document_intelligence.py \
  tests/test_cx_document_intelligence_summary_contract.py \
  --cov=nex_cx.document_intelligence \
  --cov=run_cx_document_intelligence_summary_contract \
  --cov-branch --cov-report=term-missing
./.venv/bin/python \
  scripts/smoke/run_cx_document_intelligence_summary_contract.py --summary
```

PostgreSQL and remote providers are intentionally not invoked in this contract
Slice.

Observed on 2026-09-22:

- Focused contract suite: `26 passed`.
- New module and evidence runner statement/branch coverage: 100%/100%.
- Deterministic contract evidence: `10/10` checks passed.
- Full regression: `7175 passed`, statement coverage `98.88%`, branch coverage
  `96.56%`.
- Contract validation: 85 JSON Schemas, 136 examples, 101 negative examples,
  and 7 OpenAPI documents passed.
- Full quality gate completed with exit code `0`.
