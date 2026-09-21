# Slice 0932: CX vector index profile and freshness contract

## Goal

Define the metadata-only vector-index identity, profile, fingerprint, freshness,
and transition contract before persistence and pgvector wiring.

## Contract

- An embedding profile fixes provider alias, model profile, model revision,
  deployment, vector dimension, and a deterministic profile fingerprint.
- A source snapshot fixes chunk set, chunk policy, Markdown hash, ordered chunk
  IDs/text hashes, and a deterministic source fingerprint.
- The manifest carries canonical tenant/owner lineage and never carries raw
  vectors, source text, chunk text, prompts, or provider payloads.
- Freshness states are `BUILDING`, `READY`, `STALE`, `REBUILD_REQUIRED`, and
  `FAILED`. Only a verified `READY` manifest is retrieval-usable.
- Eleven stable reason codes distinguish source, policy, model, deployment,
  dimension, count, and payload-fingerprint drift.
- `READY` requires one metadata-only payload receipt per chunk, matching vector
  dimensions, and a complete payload fingerprint.
- Six allowed transitions keep failure, stale detection, and rebuild admission
  explicit and reject stale writers or invalid state jumps.

PostgreSQL, pgvector, and the remote embedding provider are not required for
this pure domain-contract Slice.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_vector_index_freshness.py \
  tests/test_cx_vector_index_freshness_contract.py
./.venv/bin/python \
  scripts/smoke/run_cx_vector_index_freshness_contract.py --summary
```

- Focused regression: `52 passed`; contract module statement/branch coverage
  `100%/100%`.
- Contract smoke: `8/8` checks passed across `5` states, `11` stale reason
  codes, and `6` allowed transitions.
- Full quality gate: `6733 passed`; statement coverage `98.84%`; branch
  coverage `96.43%`.
