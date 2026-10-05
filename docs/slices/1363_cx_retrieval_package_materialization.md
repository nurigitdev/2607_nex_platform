# Slice 1363: CX Retrieval Package Materialization

## Goal

Reload a persisted S136 retrieval package after a CX restart without placing
private query or evidence text in PostgreSQL.

## Implementation

- `cx_retrieval_packages` now keeps canonical tenant/owner lineage, the
  permission snapshot, retrieval profile, warnings, and runtime policy metadata.
- Legacy rows with evidence are backfilled from their content-object lineage.
  Rows without provable ownership remain nullable and cannot be materialized.
- `RestartSafeRetrievalPackageStore` verifies owner scope before any private
  payload read, then reloads chunk text through the owner-scoped private store.
- Permission snapshot and evidence hashes are revalidated. Missing, duplicated,
  tampered, or cross-owner evidence fails closed.
- PostgreSQL continues to exclude raw query text, embedding vectors, and evidence
  text. The new owner index is `idx_cx_ret_pkg_owner_created`.

## Verification

```bash
scripts/quality/run_slice_gate.sh \
  --service nex-cx \
  --test tests/test_cx_retrieval_package_materialization.py \
  --coverage-target services/nex-cx/nex_cx/retrieval_materialization.py \
  --smoke scripts/smoke/run_cx_retrieval_package_materialization.py
```

Protected PostgreSQL migration and live generation-provider evidence remain
assigned to Slice 1370. Slice 1364 wires this materializer into the active CX
generation runtime composition.

Observed evidence:

- Slice Gate: `2,402 passed`
- repository statement coverage: `99.10%`
- repository branch coverage: `98.22%`
- materializer statement/branch coverage: `100%`/`100%`
- contract validation: `161` schemas, `220` examples, `188` negative
  examples, and `7` OpenAPI documents
- deterministic materialization smoke: `5/5` checks with one authorized
  private read and zero cross-owner reads
