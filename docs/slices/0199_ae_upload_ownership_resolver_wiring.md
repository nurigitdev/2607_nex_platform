# Slice 0199: AE Upload Ownership Resolver Wiring

## Scope

Slice 0199 wires the shared OA subject registry resolver into the AE upload
handoff path.

Implemented:

- AE upload route accepts an injectable ownership resolver.
- `NEX_AE_UPLOAD_OWNER_RESOLVER_MODE` controls runtime behavior.
- supported modes: `disabled`, `verify`, and `ensure`.
- default mode remains `disabled` so existing mock-first regression flows keep
  working without a live OA service.
- in `verify` and `ensure` modes, AE resolves `ownership_ref` before forwarding
  the CX upload request.
- resolver failures are returned as `ae.upload_owner_unresolved`, and CX is not
  called when ownership resolution fails.

## Runtime Modes

```text
disabled  skip OA resolver calls
verify    require existing tenant/user refs in OA before CX handoff
ensure    create/ensure local OA registry entries before CX handoff
```

The default resolver uses:

```text
NEX_OA_BASE_URL
NEX_AE_TO_OA_SERVICE_TOKEN
NEX_OA_SUBJECT_RESOLVER_TIMEOUT_SECONDS
```

## Privacy Boundary

AE forwards only stable ownership refs and legacy aliases. Resolver error
mapping preserves status/retry intent but does not include raw source content,
storage paths, tokens, emails, raw identity profiles, or other private identity
payloads.

## Next Slice

Recommended next slice:

- `0200_cx_upload_ownership_resolver_guardrail_smoke`

That slice should add the same defense-in-depth resolver guardrail on CX upload
intake and include PostgreSQL smoke evidence against `nex_cx_test`.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ae_uploads.py -q
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```
