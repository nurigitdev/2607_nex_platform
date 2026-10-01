# Slice 1216: OA subject lifecycle service API

## Goal

Expose the revisioned subject lifecycle through a service layer and a narrowly
authorized internal route.

## Behavior

- `PATCH /internal/v1/identity/tenants/{tenant_id}/subjects/{subject_id}/lifecycle`
  accepts target status, expected revision, and reason code.
- Callers need both `service:call` and `identity:lifecycle:write` scopes.
- The actor is derived from validated service claims; payloads cannot choose an
  actor, request, or trace identity.
- Unknown payload fields fail closed, protecting the route from credential or
  token material accidentally entering lifecycle evidence.
- Existing ensure and read routes are unchanged.
- The fifth-Slice Checkpoint Gate runs after Slice Gate verification.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_nex_oa_identity_lifecycle_service.py \
  --test tests/test_oa_subject_lifecycle_api.py \
  --coverage-target services/nex-oa/nex_oa/identity_lifecycle_service.py \
  --coverage-target scripts/smoke/run_oa_subject_lifecycle_api.py \
  --smoke scripts/smoke/run_oa_subject_lifecycle_api.py

./scripts/quality/run_checkpoint_gate.sh \
  --test tests/test_nex_oa_identity_lifecycle_service.py \
  --test tests/test_oa_subject_lifecycle_api.py \
  --coverage-target services/nex-oa/nex_oa/identity_lifecycle_service.py \
  --smoke scripts/smoke/run_oa_subject_lifecycle_api.py
```
