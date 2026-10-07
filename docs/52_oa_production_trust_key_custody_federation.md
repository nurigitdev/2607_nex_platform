# OA Production Trust, Key Custody, and Enterprise Federation

Status: S144 active through Slice 1441. Production deployment remains
unapproved.

## Required Outcome

S144 replaces OA's deliberately unavailable production signer with external
RSA-3072 custody, proves rotation and revocation across JWKS and introspection,
and turns the existing OIDC primitives into an operational enterprise
federation boundary. The implementation remains vendor-neutral even though the
accepted staging realization uses OpenBao Transit and the OpenBao OIDC identity
provider.

S144 starts from the immutable S142 application images and the accepted S143
single-host Docker Compose topology. Traefik remains the managed TLS boundary,
OpenBao remains an independently authenticated and policy-isolated service,
and `nex_oa_test` remains the only database used by protected acceptance.

## Single-Host Feasibility Decision

The single-host topology is sufficient for S144 staging acceptance. Physical
host separation is not required when these logical boundaries all hold:

- OA can request RSA-3072 PKCS#1 v1.5 SHA-256 signatures but cannot export or
  read private key material;
- Transit administration and signing use distinct OpenBao policies and OA
  receives sign/read-public permissions only;
- the staging OIDC issuer is reached through Traefik HTTPS and publishes real
  discovery metadata and JWKS outside the OA process;
- OIDC client credentials use S143 owner-scoped secret injection and are never
  stored in source, image, PostgreSQL, logs, or evidence;
- OA stores only public JWK material, lifecycle metadata, and an opaque custody
  reference;
- OpenBao, OA, Traefik, and PostgreSQL retain separate process, network,
  credential, and persistence boundaries; and
- protected evidence proves restart, rotation, overlap, revocation, metadata
  rollover, denial, outage recovery, rollback, privacy, and zero residue.

OpenBao is a production-shaped staging IdP adapter, not the final corporate
directory. S144 does not require contact with Microsoft Entra ID, Okta,
Keycloak, or another corporate IdP. A later production registration may replace
the issuer without changing OA's OIDC contracts or accepted claims.

No additional host package is required. The existing Docker Engine, Docker
Compose plugin, Git, and repository Python environment are sufficient.
OpenBao and Traefik remain digest-pinned OCI image dependencies.

## Existing Foundation

- OA already owns durable signing-key metadata, public JWKS projection,
  revocation digests, token introspection, and restart-safe repositories.
- `OaRsaSigningProvider` isolates JWT construction from private key custody.
- Production startup currently fails closed because only `UNAVAILABLE` and the
  explicit test-only file provider are implemented.
- OA already has strict OIDC discovery/JWKS validation, bounded caching,
  exact external-subject linking, durable provider/identity repositories, and
  OA-session issuance.
- S143 already provides owner-scoped OpenBao AppRole injection, Raft storage,
  Traefik TLS, immutable application images, and zero-residue Compose cleanup.

## Gap Register

| Gap ID | Owner | Target Slice | Required result |
| --- | --- | --- | --- |
| `external_signer_transport` | OA | `1434` | Add a bounded, TLS-validated, privacy-safe OpenBao Transit RSA signer adapter. |
| `oa_runtime_signer_wiring` | OA | `1435` | Select Transit only from explicit production-shaped configuration and fail closed otherwise. |
| `custody_key_lifecycle` | OA and platform integration | `1436` | Provision RSA-3072 keys, derive public JWK metadata, and bind opaque key versions without private export. |
| `rotation_jwks_introspection` | OA | `1437` | Prove prepublication, active/verify-only overlap, revocation, introspection, restart, and rollback; run Checkpoint Gate. |
| `federation_registration_metadata` | OA | `1438` | Register a TLS OIDC issuer/client with exact redirect, issuer, audience, and claim policy. |
| `federation_rollover_outage` | OA | `1439` | Handle metadata/JWKS rollover, unknown keys, disabled links, IdP outage, cache expiry, and recovery without fail-open. |
| `protected_single_host_acceptance` | OA and platform integration | `1440`, `1441` | Run the real Compose topology against OpenBao, Traefik, and `nex_oa_test`, including restart and zero residue. |
| `closure_attestation` | Platform integration | `1442` | Bind value-free evidence, publish the runbook, run Full Gate, close S144, and activate its S148 dependency. |

All gaps begin `OPEN`. Unit tests and local protocol doubles cannot close
`protected_single_host_acceptance`.

Slice 1434 closes the deterministic `external_signer_transport` gap. Its
OA-local adapter authenticates with AppRole, accepts only version-pinned
`vault://openbao/transit/keys/...` references, requests RSA-3072-compatible
SHA-256 PKCS#1 v1.5 signatures, verifies response version/size, redacts all
transport failures, and self-revokes its client token. Live OpenBao execution
remains part of the protected acceptance gap.

Slice 1435 closes `oa_runtime_signer_wiring`. The `OPENBAO_TRANSIT` provider is
available only in `staging_live` and `production`, reuses the S143 TLS/AppRole
file boundary, authenticates eagerly, and has no automatic fallback. The
default remains unavailable and the file provider remains test-only.

Slice 1436 closes the deterministic portion of `custody_key_lifecycle`.
Operator-only provisioning creates and reads back an exact `rsa-3072` Transit
key with derived mode, export, and plaintext backup disabled. OA registration
receives only a version-pinned opaque custody reference and the projected
public JWK. The application runtime has no key-create, rotate, export, backup,
delete, or policy capability. Live policy isolation and rotation remain for
Slices 1437 and 1441.

Slice 1437 closes the deterministic `rotation_jwks_introspection` gap. Transit
rotation requires the exact current version, new public metadata is
prepublished before activation, and the previous/new OA state transition is a
single repository transaction. A rejected activation leaves the previous key
active. JWKS overlap validates old and new tokens, revocation remains effective
after service reconstruction, and no private material enters OA persistence or
evidence. Protected OpenBao and PostgreSQL proof remains owned by Slice 1441.

Slice 1438 closes the deterministic `federation_registration_metadata` gap.
OA accepts only a production-shaped HTTPS issuer, issuer-relative discovery,
the canonical OA callback, authorization code flow with PKCE S256, confidential
client authentication, and the exact `openid` scope. OpenBao owns the client
secret and OA receives only an S143 namespace-scoped opaque reference; neither
the secret nor its reference is persisted or emitted. Discovery endpoints
must remain on the issuer origin and explicitly advertise the accepted flow,
scope, authentication method, PKCE method, and RS256 signing algorithm. Live
OpenBao registration remains owned by Slices 1440 and 1441.

Slice 1439 closes the deterministic `federation_rollover_outage` gap. An
unknown key identifier causes one bounded refresh, a refreshed JWKS is swapped
in only after discovery and every public key validate, and a JWKS URI must
remain on the HTTPS issuer origin. Expired caches never serve stale keys after
an IdP failure. The cache retains its last-good generation for diagnosis,
records redacted failure state, and clears that state only after a complete
recovery refresh. Disabled providers and disabled exact-subject links remain
fail-closed. Protected live rollover and outage proof remains in Slice 1441.

Slice 1440 closes the deterministic Compose and OpenBao configuration portion
of `protected_single_host_acceptance`. An S144 override preserves the S143 base
topology while enabling the OpenBao authorization UI, adding a Traefik-managed
HTTPS issuer route with OpenBao CA verification, selecting the Transit signer,
and injecting exact OIDC registration metadata into OA. OpenBao provisions the
non-exportable RSA-3072 Transit key, a sign/read-only OA policy, a confidential
OIDC client, KV custody for its secret, and an exact client allowlist.

OpenBao assigns the client ID; it is public opaque metadata rather than a
repository-selected identifier. OA always requires PKCE S256. OpenBao 2.7 may
omit `code_challenge_methods_supported` from discovery, so absence is accepted
while an advertised incompatible value is rejected. This does not relax OA's
authorization request policy. Protected execution remains mandatory in Slice
1441.

Slice 1441 connects the real `nex_oa_test` migration head, current immutable
OA image, OpenBao Raft/Transit/OIDC, and Traefik HTTPS boundary. The protected
runner performs authorization code exchange with PKCE S256, submits the actual
OpenBao ID token to OA's exact-subject federation service, rotates Transit and
OIDC keys, verifies JWKS overlap, revocation, restart, outage fail-closed
behavior, recovery, privacy, and cleanup. The federated-login route now uses
the configured signed-token admission runtime rather than directly parsing a
legacy mock token. Traefik reaches OpenBao only through a dedicated internal
identity network, and the ten-route managed certificate includes the identity
issuer SAN. OA uses separate AppRoles for one-use KV bootstrap and repeatable,
sign/read-only Transit authentication; the signer retries once with the latter
when its short-lived client token expires. OA restart refreshes the one-use KV
credential and recreates the container rather than weakening bootstrap reuse.
Acceptance is fail-closed: OA session issuance, an actual OIDC token `kid`
change, and old/new JWKS overlap must all be observed rather than inferred from
key-set counts.

The canonical browser callback URL remains registration metadata only; OA does
not yet expose the callback route or state-cookie/browser redirect lifecycle.
That gap is explicit in protected evidence and blocks production approval. It
does not invalidate the single-host feasibility decision or the live provider
protocol/session-boundary proof.

## Slice Sequence

| Slice | Scope |
| --- | --- |
| `1433` | Current-state audit, single-host feasibility, ownership, gaps, and non-drift rules. |
| `1434` | OpenBao Transit HTTP signer transport and strict response/redaction contract. |
| `1435` | OA runtime provider selection, TLS/AppRole authentication, and fail-closed startup wiring. |
| `1436` | External key provisioning, public JWK/version projection, and lifecycle binding. |
| `1437` | Rotation, JWKS overlap, revocation, introspection, restart, rollback, and fifth-Slice Checkpoint Gate. |
| `1438` | Enterprise OIDC registration, discovery, client, redirect, scopes, and claim policy. |
| `1439` | OIDC metadata/JWKS rollover, denial, outage, bounded cache, and recovery hardening. |
| `1440` | S144 single-host Compose assets and deterministic local trust/federation rehearsal. |
| `1441` | Protected PostgreSQL/OpenBao/Traefik trust rotation and federation acceptance. |
| `1442` | Value-free attestation, runbook, Full Gate, S144 closure, and S148 handoff. |

## Non-Drift Rules

- OA remains the only issuer of NeX user sessions and service/delegated access
  tokens. OpenBao OIDC identity is an upstream authentication assertion only.
- No service other than OA validates upstream enterprise ID tokens.
- No private signing key, OIDC client secret, user password, raw token, raw
  subject, or database URL may enter source-controlled evidence.
- Automatic linking by email or employee number remains forbidden. Federation
  requires an exact pre-provisioned external-subject digest.
- OpenBao root/admin tokens never enter OA. OA receives distinct
  least-privilege AppRole credentials for one-use KV bootstrap and runtime
  Transit signing; neither role may inherit the other's capabilities.
- PostgreSQL stores opaque custody references and public JWKs only. It never
  stores private key material or OIDC client credentials.
- `SIGNED_ONLY` remains mandatory; key or IdP outage fails closed and cannot
  activate mock or local-file fallbacks.
- S144 does not add cross-service database reads, contact production, push an
  image, or approve deployment.
- Slice Gate runs for every Slice, Checkpoint Gate at Slice 1437, and Full Gate
  at Slice 1442.

## Stop Conditions

Stop S144 before protected acceptance if OpenBao cannot keep RSA-3072 private
material non-exportable, cannot produce RS256-compatible PKCS#1 v1.5
signatures, cannot publish a TLS OIDC discovery/JWKS boundary, or cannot isolate
OA signing access from administration. Also stop on any requirement for host
network mode, Docker socket mounting, privileged application containers,
source-controlled credentials, production contact, or a silent mock fallback.
