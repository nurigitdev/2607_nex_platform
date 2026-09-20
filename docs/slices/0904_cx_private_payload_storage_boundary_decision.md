# Slice 0904: CX private payload storage boundary decision

## Goal

Freeze restart-safe ownership for the six CX private payload classes without
copying raw content or vectors into public operational tables.

## Decision

| Payload | Durable owner | Restart behavior | Status |
| --- | --- | --- | --- |
| Source bytes | local source adapter, later object storage | reload and verify by URI/hash | durable |
| Decoded source text | no separate durable copy | decode verified source bytes again | reconstructable |
| Chunk text | extracted Markdown plus chunk offsets | reconstruct and hash-verify | adapter required |
| Chunk vectors | pgvector or external vector store | load by chunk id and verify dimension/hash | adapter required |
| Summary text | private summary artifact store | load by URI and verify hash | adapter required |
| Summary vectors | pgvector or external vector store | load by summary id and verify dimension/hash | adapter required |

Private payload IO remains outside database transactions. Authorization runs
before reads, and missing or hash-mismatched payloads fail closed with a
redacted operational event. Public PostgreSQL rows retain only metadata,
hashes, dimensions, previews, lineage, and storage URIs.

The four missing adapters become the high-priority implementation input for
S92. This slice adds no table or migration.

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_cx_private_payload_boundary_decision.py --summary
./.venv/bin/pytest -q \
  tests/test_cx_private_payload_boundary_decision.py \
  tests/test_cx_persistence_gap_rebaseline.py \
  --cov=nex_cx.private_payload_boundary \
  --cov=run_cx_private_payload_boundary_decision \
  --cov-branch --cov-report=term-missing
```

Observed verification:

```text
boundary: PASS payloads=6 durable=1 reconstructable=1 adapter_required=4
focused tests: 12 passed; target statement/branch coverage: 100%
aggregate regression: 6294 passed, 1 known warning
statement=75789/76670=98.85091952523803%
branch=17660/18310=96.45002730748224%
contract validation: 82 schemas, 133 examples, 97 negative examples, 7 OpenAPI
```
