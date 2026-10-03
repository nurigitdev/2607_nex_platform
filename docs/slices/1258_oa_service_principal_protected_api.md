# Slice 1258: OA protected service-principal API and audit wiring

## Goal

Expose the S126 lifecycle through protected internal APIs with separate read
and administrative scopes and privacy-safe operational audit evidence.

## Implementation

- Added principal create/update, list, detail, and status routes.
- Added credential issue, list, detail, rotation, and status routes.
- Read routes require `service-principal:read`; mutation routes require
  `service-principal:admin`. Both also require the common service scope and
  `nex-oa` audience.
- Rejects unknown or missing payload fields before service execution.
- Emits privacy-safe operational events for every successful mutation. Raw
  client secrets and hashes are never included in audit details.
- Credential verification and token exchange remain internal and deferred to
  S127.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_nex_oa_service_principal_api.py \
  --coverage-target services/nex-oa/nex_oa/service_principal_api.py
```
