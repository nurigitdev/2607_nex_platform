# W40-CA01-S05 Fail-Closed Project Authorization Consumer Migration

## Status

`CLOSED` on 2026-11-12.

This Slice moves protected MyBee Project writes from the optional OA
`project_ids` convention to an explicit OA decision bound to the exact
`(tenant_id, subject_id, project_code, action)` tuple.

## Implemented Boundary

- Added the shared EOS `EosProjectAuthorizationGate`.
- EOS resolves the internal Project UUID to the immutable Project Code and the
  current `authorization_version` before calling OA.
- A protected write is admitted only when the EOS Project synchronization state
  is `IN_SYNC`, the version is positive, and OA returns a current allow decision
  for that exact source version.
- OA response tenant, subject, Project Code, action, correlation, minimum source
  version, global scope, Project status, grant status, event hash, and
  authorization revision are strictly rebound and validated.
- Missing Project, code mismatch, pending/failed synchronization, missing or
  revoked grant, insufficient role/scope, stale projection, malformed response,
  transport failure, and authorization revision drift all fail closed before
  the business mutation boundary.
- Installed EOS composition now binds the gate to:
  - VoucherCandidate creation;
  - Voucher Draft creation;
  - accounting/document scoped-approval requests;
  - Project membership and Project administration writes;
  - Project WorkCode approval; and
  - Project WorkAssignment management and Human performance admission.
- Added OA role policy entries for `project:project:admin`,
  `project:work-code:approve`, `project:work-assignment:manage`, and
  `finance:journal:request-approval`.

## Compatibility And Persistence

- Existing Project UUID primary and foreign keys remain unchanged.
- Project Code is the only OA authorization resource key.
- No database migration or public API field was added.
- Existing historical read paths remain under their prior compatibility
  contracts. This Slice strengthens new protected writes and does not hide
  historical records solely because a legacy Project predates OA projection.
- EOS remains Project membership SoR; OA remains authorization decision SoR.
- The installed runtime requires its existing signed EOS-to-OA service token
  with `service:call` and `authorization:read`.
- No remote model provider is required.

## Validation Evidence

Focused authorization and consumer regression:

```text
project authorization focus: 38 passed, 1 protected skip
new project_authorization.py: 100.00% statement / 100.00% branch
OA decision policy focus: 64 passed, 1 protected skip
```

Actual `nex_eos_test` and `nex_oa_test` PostgreSQL protected smoke:

```text
30 passed
database/user identity: verified for both test databases
migrations: EOS 2538 and OA 2518+ applied in isolated schemas
PENDING authorization synchronization: denied
IN_SYNC exact source version: allowed
OA grant revocation: denied
VoucherCandidate residue after denied paths: 0
temporary schema residue: 0
```

NeX-EOS Slice Gate, explicitly retaining the S04 cross-service regression:

```text
status: PASS
commands: 5/5
tests: 1562 passed, 47 protected skips
statement coverage: 96.41%
branch coverage: 94.17%
project_authorization.py: 100.00% statement / 100.00% branch
```

NeX-OA Slice Gate:

```text
status: PASS
commands: 5/5
tests: 1225 passed, 13 protected skips
statement coverage: 96.75%
branch coverage: 95.27%
project_entitlements.py: 100.00% statement / 100.00% branch
```

Machine-readable evidence:

- `reports/quality/mybee-w40-ca01-s05-eos.coverage.json`
- `reports/quality/mybee-w40-ca01-s05-oa.coverage.json`

## Operational Notes

- `NEX_EOS_OA_PROJECT_TIMEOUT_SECONDS` controls the exact Project decision
  request timeout and defaults to 10 seconds.
- Requests use no-cache headers. Long-lived tokens do not carry Project lists.
- A synchronized allow decision is not cached by EOS; revocation is observed on
  the next protected write.
- S04 entitlement delivery must remain in the EOS Slice Gate test set because
  its cross-service test filename is outside the default `test_nex_eos_*` glob.

## Next Entry

`W40-CA01-S06` closes lifecycle revocation, versioned reconciliation, and the
W40 entry gate across actual EOS/OA PostgreSQL state.
