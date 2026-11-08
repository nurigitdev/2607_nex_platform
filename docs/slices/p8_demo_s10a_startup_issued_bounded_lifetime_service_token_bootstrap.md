# P8-DEMO-S10A: Startup-Issued Bounded-Lifetime Service Token Bootstrap

## Outcome

The Demo deployment no longer depends on a bearer token remaining valid from
the time it was written to OpenBao. Each non-OA backend owner resolves one OA
service-principal credential at container startup and exchanges that
credential for the exact audience/scope tokens declared by the existing Demo
trust grants. The credential values are removed before the packaged service
process is executed.

This is a deliberately bounded Demo exception. It does not change the
canonical production `service_access` profile:

```text
production service_access       = 300 seconds (unchanged)
P8 Demo p8_demo_service_access  = 86,400 seconds maximum
deployment boundary             = P8_DEMO
runtime profile                 = staging_live
activation setting              = STARTUP_24H
```

One-year bearer tokens are not admitted.

## Security Boundary

The additive token use `p8_demo_service_access` requires signed claims for the
exact Demo deployment boundary and profile. OA issues this profile only when
all three settings agree. Cross-service verifiers reject it by default and
accept it only under the same explicit Demo configuration.

OA starts and becomes healthy before dependent backend containers perform
their exchange. Every non-OA owner receives:

- the audience/scopes already frozen in `DEMO_TRUST_GRANTS`; and
- one OA-audience `token:introspect` token for sensitive-route admission.

The bootstrap validates the OA signature through JWKS, audience, scope,
service-principal identity, exact 24-hour lifetime, and profile claims before
placing a token in the child process environment. Failure to resolve the
credential, contact OA, verify JWKS, or bind the response fails startup closed.

Raw credentials and bearer tokens are excluded from result objects, logs, and
reports. Existing S08's 31-binding inventory remains immutable historical
evidence; two startup credential references per non-OA owner are an additive
S10A input. Previously materialized static trust-token slots are overwritten
before process execution and are not authoritative after S10A activation.

## Runtime and Persistence

- No database migration or API field was added.
- OA service-principal and signing-key tables remain the system of record.
- OpenBao remains the custody boundary for client credential material and the
  RSA signing key.
- Existing outbound environment variable names remain unchanged, avoiding a
  client-adapter rewrite before the Demo.
- Restarting a dependent service performs a fresh exchange. It does not reuse
  a token captured by an earlier process.

## Verification

```text
focused Slice Gate       = 1,241 passed / 11 protected skips
statement coverage       = 98.55%
branch coverage          = 97.78%
Compose render           = PASS, 15 services / 8 images
secret in Compose report = false
production 300s profile  = unchanged
default Demo-token deny  = verified
credential scrubbing     = verified
token/report redaction   = verified
```

Actual OA PostgreSQL principal provisioning, OpenBao credential population,
and installed cross-service calls remain part of P8-DEMO-S10. S10A closes the
runtime mechanism and policy needed by that protected execution; it does not
claim the installed journey has already run.

## Post-Demo Backlog

Before this profile can be promoted beyond the Chairman Demo, replace the
startup-only compromise with a production lifecycle design:

1. Keep the normal 300-second access-token profile and implement refresh ahead
   of expiry with bounded jitter and retry.
2. Swap tokens atomically in long-lived HTTP clients without process restart.
3. Add expiry/readiness metrics, refresh-failure alerting, and fail-closed
   behavior when the remaining lifetime crosses a safety floor.
4. Exercise overlapping service-credential rotation, revocation propagation,
   signing-key rotation, restart, and multi-instance refresh convergence.
5. Remove the transitional static trust-token secret slots from the Demo
   inventory after migration evidence proves that all callers use credential
   exchange.
6. Restore the 300-second profile in the normal staging/production topology;
   `STARTUP_24H` must remain rejected outside `P8_DEMO + staging_live`.

This backlog is required production hardening, not an optional token-lifetime
increase.
