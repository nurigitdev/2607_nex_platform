# OA Production Trust and Federation Runbook

## Purpose

This runbook reproduces the S144 repository audits, single-host trust
rehearsal, protected PostgreSQL/OpenBao/Traefik acceptance, closure, and Full
Gate. A pass proves the production-shaped OA signing-custody and enterprise
OIDC protocol boundary in non-production staging. It does not approve a
registry push, corporate IdP registration, or production deployment.

## Software Boundary

No host installation of OpenBao or Traefik is required. The staging host needs
only Docker Engine, the Docker Compose plugin, Git, and the repository Python
environment. OpenBao and Traefik use the digest-pinned S143 images. The only
external data dependency is the existing `nex_oa_test` PostgreSQL database.
DGX providers are outside S144.

Do not put database URLs, OpenBao credentials, OIDC credentials, raw subjects,
sessions, or signed assertions in Compose `.env` files, source, logs, or
attestations. Inject protected values through the approved operator process.

## Repository Audits

Run from the repository root:

```bash
./.venv/bin/python scripts/smoke/run_s144_oa_production_trust_boundary.py --summary
./.venv/bin/python scripts/smoke/run_oa_openbao_transit_signer.py --summary
./.venv/bin/python scripts/smoke/run_oa_openbao_transit_runtime.py --summary
./.venv/bin/python scripts/smoke/run_oa_openbao_transit_key_lifecycle.py --summary
./.venv/bin/python scripts/smoke/run_oa_openbao_transit_rotation_checkpoint.py --summary
./.venv/bin/python scripts/smoke/run_oa_enterprise_oidc_registration.py --summary
./.venv/bin/python scripts/smoke/run_oa_oidc_rollover_resilience.py --summary
./.venv/bin/python scripts/smoke/run_s144_staging_trust_rehearsal.py --summary
```

All eight commands must report `pass`. This deterministic layer verifies the
provider-neutral signer contract, strict production profile admission,
non-exportable key metadata, atomic rotation, enterprise OIDC registration,
rollover/outage behavior, and exact ten-route Compose topology.

## OCI Release Set

Rebuild the complete release set on a clean committed tree when included
source, dependencies, Containerfiles, or deployment inputs change:

```bash
NEX_PLATFORM_OCI_IMAGE_BUILD=1 \
./.venv/bin/python scripts/deployment/build_platform_images.py \
  --execute --summary
```

Require six immutable non-root images, seven successful background process
checks, a complete release set, no registry push, and no production contact.

## Protected Acceptance

Inject `NEX_OA_TEST_DATABASE_URL` without persisting it, then run:

```bash
NEX_S144_PROTECTED_ACCEPTANCE=1 \
./.venv/bin/python \
  scripts/smoke/run_s144_protected_trust_federation_acceptance.py \
  --execute --summary
```

The command must use the actual `nex_oa_test` identity and migration head. It
must prove RSA-3072 Transit custody and rotation, OA JWKS overlap, revocation,
restart reconstruction, OpenBao outage fail-closed behavior, recovery,
authorization code plus PKCE, ID assertion verification, exact-subject
resolution, OA session issuance, OIDC signing-key rollover, and old/new JWKS
overlap. A false required signal fails the run.

The ignored report is written to
`reports/deployment/s144-protected-trust-federation.json`. Verify that the run
leaves no S144 rows in `nex_oa_test` and no Compose containers, networks, or
volumes. The tracked attestation keeps only source, release-set,
configuration/report digests, counts, booleans, and zero-residue metadata.

## Closure and Full Gate

```bash
./.venv/bin/python \
  scripts/smoke/run_s144_oa_production_trust_closure.py \
  --summary
scripts/quality/run_quality_gate.sh
```

Closure must report eight of eight audits, eight closed gaps, two Transit
versions, two OIDC JWKS keys, ten managed routes, one actual database, and
`next=S145`. Full Gate leaves the protected runner's opt-in disabled and
validates the already accepted source-controlled attestation through the
closure runner.

## Failure and Recovery

1. A Transit login, version, algorithm, or signature mismatch blocks OA token
   issuance. Do not activate a local signer or test-file fallback.
2. An OIDC discovery, issuer-origin, JWKS, nonce, audience, or exact-subject
   mismatch blocks federation. Do not link by email or employee number.
3. During key rotation, prepublish the new public key before activation and
   retain the previous verification key through the overlap window. Roll back
   activation metadata if any acceptance signal fails.
4. OpenBao outage must return a controlled failure. Restore OpenBao, unseal it,
   refresh the appropriate least-privilege AppRole credential, recreate OA,
   and verify readiness before retrying.
5. Always run the same Compose project with `down --volumes --remove-orphans`
   after interruption. Remove run-scoped OA data and confirm zero residue.

## Deferred Browser Boundary

S144 proves the upstream OIDC provider protocol and OA verification/session
boundary. The canonical browser callback route, state-cookie lifecycle, and
redirect experience remain explicit S149 integrated-staging prerequisites.
This deferral blocks production approval and cannot be interpreted as an
implemented browser login journey.

## Handoff

S144 closes external OA signing custody and enterprise federation staging
acceptance. Its value-free evidence is ready as an S148 observability input.
S145 remains the next implementation requirement. Corporate IdP onboarding,
registry publication, and production approval remain outside this closure.
