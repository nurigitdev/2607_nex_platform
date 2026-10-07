# Slice 1440: S144 Staging Trust Rehearsal

## Outcome

- Added an S144 override on the accepted S143 single-host Docker Compose base.
- Enabled the OpenBao authorization UI and exposed its OIDC provider only
  through Traefik HTTPS with the private OpenBao CA and exact server name.
- Added non-exportable RSA-3072 Transit provisioning and an OA policy limited
  to owner KV reads, exact signing, and public key metadata reads.
- Added confidential OpenBao OIDC client registration, generated client ID
  handoff, client-secret KV custody, exact callback, and provider allowlisting.
- Reconciled OA registration with OpenBao 2.7: client IDs are externally
  generated and PKCE S256 remains mandatory even when discovery omits its
  optional capability field.

## Composition Decision

The S143 base Compose file and its evidence remain unchanged. S144 uses one
override file and replacement OpenBao/Traefik configuration files, so operators
can still run or audit the earlier configuration independently. The merged
Compose configuration was validated by the real `docker compose config`
command without starting containers.

The OIDC client secret never enters Compose, source, evidence, PostgreSQL, or
the OA provider record. The S144 bootstrap administrator writes it directly to
OpenBao KV and returns only its version. OA receives an opaque reference at its
process boundary; actual protected materialization and use are owned by Slice
1441.

## Verification

- Focused Compose, OpenBao configuration, OIDC registration, and evidence
  tests pass (`61 passed`; `95 passed` including contract-validator regression).
- Deterministic rehearsal passes 16/16 checks across nine simulated OpenBao
  management requests and ten managed TLS routes.
- `docker compose -f s143-staging.compose.yaml -f
  s144-staging.override.yaml config --quiet` passes with protected values
  represented only by runtime placeholders.
- No live OpenBao, PostgreSQL, corporate IdP, or production endpoint was
  contacted.
- OA Slice Gate passes with `1103 passed`, `11 skipped`, statement coverage
  `98.55%`, and branch coverage `97.98%`. The S144 staging runtime, OIDC
  registration, and rehearsal runner each retain 100% statement and branch
  coverage.
- OpenAPI 3.1 validation now uses an I/O-free document URN and a deterministic
  package-schema validator, preventing lazy C YAML-loader state from changing
  long-running coverage-gate results.
