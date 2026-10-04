# Platform OA-backed Trust Integration

Status: S134 complete; protected trust evidence, operations hardening, and the
Full Gate passed through Slice 1341.

This document is the canonical non-drift record for S134. It connects the
restart-safe test topology proven by S133 to one OA-backed user and service
trust chain without changing service ownership or weakening the default
fail-closed signing posture.

## Required Outcome

S134 must prove one actual loopback HTTP journey in which:

- a real OA local credential login creates an opaque OA user session;
- AE owns the HTTP-only browser cookie and derives owner context only from OA session introspection;
- OA service principals exchange client credentials for audience-bound RS256 service tokens;
- AE, CX, MO, and AG verify those tokens through OA JWKS and require OA introspection on sensitive route classes;
- request and trace identifiers cross every exercised service boundary;
- wrong audience, missing scope, revoked session, and revoked service token requests fail closed; and
- PostgreSQL state and trust decisions remain correct after a fresh process restart, followed by residue-free cleanup.

## Trust Invariants

- OA remains the sole identity, session, service-principal, signing-key, JWKS, introspection, and revocation authority.
- Browser credentials and opaque user sessions are never propagated to CX, MO, or AG. AE translates validated user context into owner headers and uses its own audience-bound service identity for downstream calls.
- Services never read the OA database. Signed-token verification uses the OA HTTP JWKS endpoint; sensitive operations additionally use the OA HTTP introspection endpoint.
- The default OA signing provider remains unavailable. S134 may activate an explicit test-profile file-backed provider whose temporary private key is outside the repository and removed after the protected smoke.
- No raw password, client secret, session id, service token, private key, or database URL may appear in committed evidence.
- Remote model providers are outside S134 and must not be contacted.

## Current Gaps

1. OA user-login and user-session route guards validate only legacy mock service claims instead of the shared signed-token admission runtime.
2. The OA application intentionally wires an unavailable signing provider and has no explicit test-profile external custody adapter.
3. AE OA-session mode and signed outbound service identity are independently implemented but have not been exercised together through actual processes.
4. Existing cross-service trust evidence invokes consumers in-process and does not prove the user-login-to-downstream HTTP chain, denial behavior, restart, and five-database cleanup in one protected execution.

## Slice Sequence

1. `1332`: boundary and current-state gap audit.
2. `1333`: OA signed admission for internal user/session routes.
3. `1334`: explicit test-profile file-backed signing custody.
4. `1335`: AE OA-backed signed login and trust propagation.
5. `1336`: typed evidence/privacy model and Checkpoint Gate.
6. `1337`: downstream signed scope and authorization denial flows.
7. `1338`: JWKS, introspection, revocation, and restart orchestration.
8. `1339`: actual five-database loopback HTTP protected smoke.
9. `1340`: contracts, privacy, cleanup, and operations runbook.
10. `1341`: S134 closure, Full Gate, and S135 handoff.

## Completion Signal

S134 is complete only when an actual OA credential login and OA-issued signed service-token chain reaches AE, CX, MO, and AG, while revoked and unauthorized requests fail closed before and after restart. All five test databases and all temporary key files must be clean after the evidence run.

## Slice 1339 Protected Evidence

- All five service-owned test databases reached their 89 migration heads.
- Five API processes completed two fresh startup generations over loopback HTTP.
- The exact five trust hops and four fail-closed denial scenarios passed.
- The OA user session, signing key, and revoked service-token decision survived
  restart.
- Correlated audit rows, seeded identity/trust rows, and temporary signing key
  material were removed; post-run residue was zero.
- Remote model providers were not contacted because they are outside S134.

The integrated trust path is now proven. Slice 1340 owns contract, privacy,
cleanup, and operator-runbook hardening; Slice 1341 owns final closure and the
Full Gate.

## Slice 1340 Operations Hardening

- Published the signed OA user-login response and privacy-safe active service
  claim schemas with indexed positive and negative fixtures.
- Added the signed internal user-login route to OA OpenAPI and the sensitive
  active-claim route to AE, CX, MO, and AG OpenAPI with exact route class,
  scope, and fail-closed response contracts.
- Added an operator runbook for protected execution, triage, cleanup,
  rollback, secret handling, and the explicit remote-provider boundary.
- Automated 11 contract, privacy, cleanup, documentation, and boundary checks;
  all passed without embedding connection values or secret material.
- Contract validation passed for 158 schemas, 216 examples, 186 negative
  examples, and seven OpenAPI documents.

Slice 1340 owns contract, privacy, cleanup, and operator-runbook hardening and
is complete. Slice 1341 owns final closure, the repository Full Gate, and the
S135 handoff.

## Slice 1341 Closure

- Replayed five deterministic S134 evidence components and retained the actual
  PostgreSQL smoke as protected opt-in evidence during ordinary regression.
- Bound the actual five-database, two-generation result from Slice 1339 to the
  contract, privacy, cleanup, and runbook checks from Slice 1340.
- Verified five trust hops, four denial scenarios, two restart generations,
  five isolated databases, and zero seeded-row or temporary-key residue.
- Kept OA as the trust authority, service-local database ownership intact, and
  remote model providers outside the S134 execution boundary.

Completion signal: Met. OA-backed user login, opaque browser session handling,
signed service trust, JWKS/introspection, revocation, authorization denial,
restart, privacy, and cleanup are closed for the platform MVP trust path.

## S135 Handoff

S135 is the next active requirement. It inherits only validated OA session
owner context and signed service identity. It owns authenticated document
upload-to-index durability and must not reopen identity, signing, or
cross-service trust ownership.
