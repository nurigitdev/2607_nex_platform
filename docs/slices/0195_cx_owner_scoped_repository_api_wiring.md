# Slice 0195: CX Owner-Scoped Repository API Wiring

## Scope

Slice 0195 moves CX repository behavior onto the canonical OA ownership ref
columns introduced in Slice 0194 while preserving the current legacy upload API
shape.

Implemented:

- `build_content_object_record()` now emits an `ownership_ref` envelope with
  `oa.tenant` and `oa.user` refs.
- `SqlAlchemyCxContentRepository.save_content_object()` writes decomposed
  `tenant_ref_*`, `owner_subject_ref_*`, and `uploaded_by_subject_ref_*`
  columns directly.
- active duplicate lookup uses the canonical owner ref columns instead of only
  `tenant_id + owner_user_id`.
- owner ACL rows write and dedupe with `principal_ref_type/id` and
  `granted_by_subject_ref_type/id`.
- legacy records that omit `ownership_ref` are normalized at the repository
  boundary for compatibility.
- SQLite smoke fixtures and protected smoke seed scripts now populate the
  canonical columns explicitly.

## Compatibility

The public upload path still accepts legacy `tenant_id` and `owner_user_id`.
Those values are mapped to:

```text
tenant_ref = { type = oa.tenant, id = tenant_id }
owner_subject_ref = { type = oa.user, id = owner_user_id }
uploaded_by_subject_ref = { type = oa.user, id = uploaded_by_user_id || owner_user_id }
```

This keeps same-owner duplicate prevention stable while allowing the next API
slice to pass OA subject context explicitly from AE.

## Privacy Boundary

Repository records persist stable subject references only. They do not store raw
identity payloads, auth tokens, source bytes, extracted text, chunk text,
summaries, prompts, or raw vectors.

## Next Slice

Recommended next slice:

- `0196_ae_upload_ownership_propagation_contract`

That slice should make the AE-to-CX upload contract propagate OA tenant/subject
context explicitly while keeping the legacy aliases as compatibility fields.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_cx_repository.py tests/test_nex_cx_ingestion.py tests/test_smoke_helpers.py -q
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```
