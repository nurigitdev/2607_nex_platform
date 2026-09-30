# Slice 1178: MO Catalog Runtime Route Resolution

## Scope

- Add a replaceable provider route source while retaining the static registry as
  the deterministic bootstrap/default source.
- Project active catalog bindings into the existing immutable `ProviderRoute`
  contract.
- Configure the NeX-MO runtime to resolve provider requests from the catalog
  lifecycle service.
- Preserve the route identifiers and wire shape of the three bootstrap routes.
- Fail closed with a retryable, privacy-safe `503` when durable catalog state
  cannot be read or is internally inconsistent.

## Runtime behavior

`resolve_provider_route` and `list_provider_routes` obtain a fresh snapshot from
the configured source for each request. An atomic alias replacement is therefore
visible to the next provider request without restarting NeX-MO. Explicit route
sequences still bypass the configured source for deterministic unit tests and
specialized readiness evaluation.

The static `DEFAULT_PROVIDER_ROUTES` tuple remains the source used before runtime
configuration and the seed used when an empty catalog is bootstrapped. A durable
catalog read failure does not silently fall back to static state because doing so
could route work to a model that an operator has already superseded.

## Evidence

```bash
./.venv/bin/python scripts/smoke/run_mo_catalog_route_resolution.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo
```

Expected evidence includes bootstrap compatibility, immediate active-alias
switch visibility, deterministic binding-derived route identity, privacy-safe
failure mapping, and coverage at or above the prior NeX-MO Slice Gate baseline.
