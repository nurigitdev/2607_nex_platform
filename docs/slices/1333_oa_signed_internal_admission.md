# Slice 1333: OA signed internal admission

## Outcome

- Added one OA service-auth boundary backed by the shared service-token
  admission runtime.
- Routed credential login and every internal user-session operation through
  audience, scope, signature, and credential-class introspection checks.
- Preserved deterministic TEST_MOCK compatibility when no protected admission
  runtime is attached.
- Kept admitted claims on request state without exposing the raw token.

## Verification

- Unit coverage includes signed acceptance, introspection, missing-token
  denial, mock compatibility, and missing-context failure.
- Existing OA login and session regressions remain unchanged.

