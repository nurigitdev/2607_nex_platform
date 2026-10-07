# Slice 1439: OA OIDC Rollover and Resilience

## Outcome

- Restricted discovery-selected JWKS endpoints to the exact HTTPS issuer
  origin and rejected credentials, query strings, fragments, roots, and
  malformed ports.
- Made cache refresh replacement atomic and prevented a first unknown key from
  triggering duplicate discovery/JWKS fetches in one verification attempt.
- Added privacy-safe refresh generation, outcome, failure time, and consecutive
  failure diagnostics without exposing key identifiers or remote documents.
- Proved key rollover, retired-key denial, expired-cache outage denial,
  last-good generation preservation, recovery, and disabled provider/link
  denial.

## Availability Decision

An unexpired cached key may continue to verify a token. Once the TTL expires,
OA must complete discovery and JWKS refresh before accepting another token;
an IdP outage therefore denies authentication instead of serving stale trust.
A failed refresh does not replace the last-good generation, but that generation
is diagnostic state only until a full recovery refresh succeeds.

Unknown-key refresh supports normal IdP rotation. The cache validates the full
replacement set before publishing it, so malformed metadata, cross-origin
JWKS, private JWK members, duplicate identifiers, or invalid RSA keys cannot
partially alter active trust.

## Verification

- Focused cache, verifier, federation login, and identity tests pass
  (`67 passed`).
- Deterministic evidence passes 14/14 checks with four successful refresh
  generations and a simulated IdP outage/recovery.
- The OA Slice Gate passes with `1082 passed` and `11 skipped`; statement
  coverage is 98.54% and branch coverage remains 97.93%. The new evidence
  runner retains 100% statement and branch coverage.
- Live OpenBao, Traefik, and PostgreSQL were not contacted; those checks remain
  mandatory in Slice 1441.
