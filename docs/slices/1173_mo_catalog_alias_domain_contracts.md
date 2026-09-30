# Slice 1173: MO catalog and alias domain contracts

## Goal

Define storage-neutral, immutable catalog entry and alias binding contracts with
strict lifecycle, identity, lineage, token-limit, and privacy validation.

## Result

- Added validated `ModelCatalogEntry` and `AliasBinding` value objects for
  embedding, reranking, and generation capabilities.
- Added optimistic catalog and binding revisions, explicit lifecycle states,
  append-only previous-binding lineage, and bounded change reasons.
- Included public route metadata needed for later runtime resolution while
  excluding connection configuration and operator identity from projections.
- Added deterministic bootstrap conversion for the three existing static routes
  and cross-record validation for active catalog and alias integrity.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_catalog_lifecycle_domain.py
./.venv/bin/python \
  scripts/smoke/run_mo_catalog_lifecycle_domain.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo
```
