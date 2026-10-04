# Platform OA-backed Trust Integration

Status: S134 in progress; boundary frozen by Slice 1332.

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

## S135 Handoff

S135 inherits only validated OA session owner context and signed service identity. It owns authenticated document upload-to-index durability and must not reopen identity, signing, or cross-service trust ownership.

