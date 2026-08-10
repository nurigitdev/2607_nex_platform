# Slice 0196: AE Upload Ownership Propagation Contract

## Scope

Slice 0196 updates the existing `nex-ae-api` upload handoff facade so AE
propagates canonical OA ownership refs to CX while preserving legacy owner
aliases.

Implemented:

- `build_upload_ownership_ref()` in AE upload handling.
- AE-to-CX upload payloads now include `ownership_ref` plus compatibility
  `tenant_id` and `owner_user_id`.
- direct canonical refs are accepted through `ownership_ref`, `tenant_ref`,
  `owner_subject_ref`, and `uploaded_by_subject_ref`.
- legacy aliases `tenant_id`, `owner_user_id`, `user_id`, and
  `uploaded_by_user_id` remain accepted.
- canonical refs and legacy aliases are checked for conflicts when both are
  supplied.
- `ae_upload_handoff.v1` now records the propagated `ownership_ref`.
- OpenAPI and examples document the ownership propagation contract.

## Current AE Status

`nex-ae-api` already has an implemented upload facade:

- `POST /api/v1/uploads`
- `GET /api/v1/uploads/{upload_handoff_id}`
- CX upload client with service-token forwarding
- safe upload handoff records
- document library composition from upload handoffs

This slice does not create the AE service from scratch. It extends the existing
AE upload path so future CX canonical ownership intake can consume stable OA
subject refs directly.

## Compatibility

AE continues to send legacy fields:

```text
tenant_id
owner_user_id
```

AE now also sends:

```text
ownership_ref.tenant_ref = { type = oa.tenant, id = tenant_id }
ownership_ref.owner_subject_ref = { type = oa.user, id = owner_user_id }
ownership_ref.uploaded_by_subject_ref = { type = oa.user, id = uploaded_by_user_id || owner_user_id }
```

If canonical refs and legacy aliases disagree, AE rejects the upload request
with `ae.upload_owner_invalid` instead of silently uploading under the wrong
owner.

## Privacy Boundary

The propagated ownership ref stores stable subject IDs only. AE handoff records
still exclude raw source content, source bytes, storage keys, filesystem paths,
passwords, tokens, emails, phone numbers, raw external identity profiles, and
other identity secrets.

## Next Slice

Recommended next slice:

- `0197_cx_upload_canonical_ownership_intake`

That slice should make CX upload registration consume `ownership_ref` directly
for document IDs, duplicate detection, and repository records while retaining
legacy aliases.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ae_uploads.py tests/test_contract_validation.py tests/test_nex_cx_source_ownership.py tests/test_nex_cx_persistence_audit.py tests/test_nex_cx_processing_persistence.py tests/test_nex_oa_subjects.py -q
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```
