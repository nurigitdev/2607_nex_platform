# Slice 1335: AE OA-backed signed login activation

## Outcome

- Materialized AE `mock` authentication only for `local_mock`; every protected
  runtime profile now selects OA-backed credential/session mode.
- Materialized profile-aware browser cookie security. Test loopback HTTP uses
  `Secure=false`, while local-live, staging, and production require
  `Secure=true` and reject a downgrade.
- Preserved the AE-to-OA signed service-token resolver and its fail-closed
  behavior when the configured OA audience token is absent.
- Updated the historical trust-coupling audit to recognize the signed OA route
  admission and protected browser-auth defaults as hardened controls.

## Verification

- Regression covers runtime overlays, conflicting profile settings, secure
  cookie emission, invalid boolean values, and live-profile downgrade denial.
- No database or remote model provider is required for this Slice.

