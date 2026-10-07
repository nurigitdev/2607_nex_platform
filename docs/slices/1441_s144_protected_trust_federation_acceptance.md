# Slice 1441: S144 Protected Trust and Federation Acceptance

## Outcome

- Added an opt-in protected acceptance runner for the accepted S143/S144
  single-host Docker Compose topology.
- Bound the run to the actual `nex_oa_test` database identity and current OA
  migration head.
- Exercised OpenBao userpass authentication, authorization code exchange,
  PKCE S256, OIDC discovery/JWKS, and an actual upstream ID token.
- Connected Traefik and OpenBao through a dedicated internal `identity`
  network and issued the managed TLS certificate with all ten S144 route SANs.
- Split one-use KV bootstrap credentials from a least-privilege OA Transit
  AppRole. The signer uses separate Docker secret files and re-authenticates
  once when its short-lived runtime token expires.
- OA restart acceptance refreshes the one-use bootstrap AppRole secret and
  force-recreates the container, matching the established S143 rotation path.
- Routed the OA federated-login boundary through the configured signed-token
  admission runtime. A production-shaped profile can no longer authorize this
  route with the legacy mock-token parser.
- Exercised non-exportable RSA-3072 Transit signing, version rotation,
  prepublication/JWKS overlap, token introspection, revocation, OA restart,
  OpenBao outage fail-closed behavior, recovery, and zero-residue cleanup.

## Protected Execution

The runner is disabled unless both `--execute` and
`NEX_S144_PROTECTED_ACCEPTANCE=1` are supplied. It requires the current
six-image S142 release-set evidence and `NEX_OA_TEST_DATABASE_URL`. The runner
starts only OpenBao, Traefik, and OA; it does not contact DGX providers,
production databases, a corporate identity provider, or a registry.

```bash
NEX_S144_PROTECTED_ACCEPTANCE=1 \
  ./.venv/bin/python \
  scripts/smoke/run_s144_protected_trust_federation_acceptance.py \
  --execute --summary
```

Evidence is written to
`reports/deployment/s144-protected-trust-federation.json`. It contains only
versions, counts, booleans, digests, public issuer metadata, and decisions.
Database URLs, OpenBao credentials, OIDC client/user credentials, raw
subjects, ID tokens, OA access tokens, session IDs, and private key material
are rejected from evidence.

## Federation Boundary

Protected acceptance obtains an authorization code directly from OpenBao's
authenticated provider API and exchanges it through the Traefik HTTPS issuer
route. OA validates the resulting ID token against live discovery and JWKS,
resolves only a pre-provisioned exact subject digest, and issues its own opaque
session. OpenBao remains an upstream assertion authority; OA remains the NeX
session and access-token authority.

The canonical browser callback path is registered but is not yet implemented
as an OA HTTP route. This Slice therefore proves the provider protocol and OA
verification/session boundary, not a browser redirect experience. The
protected evidence sets `browser_callback_route_implemented=false`, keeps
production deployment unapproved, and carries this explicit dependency into
the S144 closure/S148 handoff.

## Cleanup and Failure Rules

- Compose containers, networks, and the OpenBao Raft volume are removed in a
  `finally` boundary.
- OA sessions, exact identity links, provider records, service credentials,
  signing-key metadata, revocations, memberships, subjects, tenants, and
  run-scoped audit events are removed from `nex_oa_test`.
- Transit or IdP unavailability must return a controlled failure. No test-file
  signer, local key, mock provider, or unsigned-token fallback is allowed.
- A failed cleanup, stale OCI release set, database identity mismatch, private
  material leak, missing OA session, unchanged OIDC signing `kid`, or missing
  JWKS rotation/overlap signal fails the protected run.

## Verification

- Focused unit and orchestration tests cover opt-in, value-free evidence,
  signed admission, PKCE/token handoff, rotation, restart, outage, recovery,
  cleanup, and failure branches.
- Actual protected execution is required before Slice 1441 is accepted.
- Production deployment remains unapproved regardless of the staging result.
