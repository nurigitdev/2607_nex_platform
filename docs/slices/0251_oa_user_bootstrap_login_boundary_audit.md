# Slice 0251: OA User Bootstrap/Login Boundary Audit

## Scope

Freeze the OA login boundary before adding credential persistence and a real
login API. The MVP company login mode is employee id plus password.

## Decision

- Selected MVP login mode: `employee_id_password`.
- `employee_id` is the company login identifier.
- `password` is the login secret and must only be consumed by the OA credential
  verifier.
- Bootstrap accounts are operator-seeded employee accounts for now.
- External IdP/SSO, MFA, HR roster sync, password reset email, and self-service
  signup remain deferred.
- AE Web may collect employee id/password and send it to AE API over the login
  facade, but AE must not persist passwords.
- AE API delegates login verification to OA, then keeps only the opaque OA
  session id in the HttpOnly browser cookie.
- OA owns credential records, password hash verification, subject membership
  lookup, session issuance, and auth audit events.

## Implemented

- Added `nex_oa.bootstrap_login_boundary`.
- Added protected endpoint:
  `GET /internal/v1/auth/user-bootstrap-login-boundary`.
- The report fixes:
  - company login mode
  - OA/AE/AE Web authority split
  - employee id subject-mapping policy
  - credential record policy
  - safe login request/response fields
  - forbidden payload classes
  - next implementation sequence
- The report remains redaction-safe and includes no raw passwords, password
  hashes, tokens, cookies, service credentials, provider secrets, database URLs,
  or example employee passwords.

## Subject Mapping

The employee id is treated as an OA credential lookup alias. Downstream services
should consume stable `oa.user` subject refs and not depend on password-era
credential fields. Whether a deployment chooses an opaque subject id or a
normalized employee id as the subject id remains an OA-owned policy, but CX/AE
should only depend on the stable subject ref contract.

## Next Sequence

- `Slice 0252`: OA local credential registry foundation.
- `Slice 0253`: OA user login API foundation.
- `Slice 0254`: OA user login PostgreSQL smoke evidence.
- `Slice 0255`: AE auth facade credential-login adapter.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_oa_bootstrap_login_boundary.py -q`
  - Result: `4 passed, 1 warning`
- OA boundary regression:
  `./.venv/bin/pytest tests/test_nex_oa_bootstrap_login_boundary.py tests/test_nex_oa_auth_boundary.py tests/test_nex_oa_credential_delivery.py -q`
  - Result: `10 passed, 1 warning`
- Full regression and quality gate:
  `./scripts/quality/run_quality_gate.sh`
  - Result: `1775 passed, 1 warning`
  - Statement coverage: `98.14%`
  - Branch coverage: `94.29%`
