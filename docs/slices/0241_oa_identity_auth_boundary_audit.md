# Slice 0241: OA Identity/Auth Boundary Audit

## Scope

Freeze the current OA/AE/CX identity and browser-auth boundary before adding
durable OA membership persistence and OA-backed session issuance.

## Implemented

- Added a protected `GET /internal/v1/identity-auth-boundary` endpoint on
  `nex-oa`.
- Published the current and target authority split as safe decision evidence.
- Kept raw auth data out of the report: no passwords, raw tokens, cookies,
  provider endpoints, database URLs, or external profile payloads.

## Boundary

- `nex-oa` owns stable tenant/user subject references, the subject registry, and
  future session issuance/introspection.
- `nex-ae-api` owns the browser session facade, AE route guard, and propagation
  of owner-scope claims derived from authenticated sessions.
- `nex-cx` owns content owner-scope enforcement, content ACL entries, and
  retrieval evidence persistence.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_runtime_problem.py tests/test_nex_oa_auth_boundary.py tests/test_nex_oa_subjects.py -q`
  - Result: `17 passed, 1 warning`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
  - Result: `1713 passed, 1 warning`
  - Coverage: statement `98.06%`, branch `93.99%`
  - Contract validation: `pass` with 49 schemas, 78 examples, 54 negative
    examples, and 7 OpenAPI specs.
