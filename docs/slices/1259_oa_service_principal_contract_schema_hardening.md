# Slice 1259: OA Service Principal Contract/Schema Hardening

## Outcome

NeX-OA service-principal and client-credential lifecycle routes now have canonical
JSON Schema and OpenAPI coverage. The nine protected operations preserve the
`service:call` boundary and require either `service-principal:read` or
`service-principal:admin`.

## Privacy boundary

- Public principal and credential projections reject secret hashes and raw secrets.
- A raw client secret is allowed only at the root of issue and rotation responses.
- Those responses require `secret_display: once`; subsequent detail/list responses
  expose only the six-character hint.
- Positive and negative fixtures cover all six public response shapes.
- Runtime FastAPI responses are validated against the same canonical schemas.

## Evidence

Run:

```bash
./.venv/bin/python scripts/smoke/run_oa_service_principal_contracts.py --summary
./.venv/bin/python scripts/quality/validate_contracts.py
```

The S126 operations reduce known NeX-OA runtime/OpenAPI drift from 30 to 21.
The remaining routes belong to previously classified OA contract work and are not
expanded by this slice.
