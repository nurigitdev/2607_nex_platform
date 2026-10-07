# Slice 1429: Platform Production TLS Lifecycle

## Outcome

- Fixed production TLS termination to managed ingress or service mesh with
  HTTPS required end to end.
- Prohibited application-container private-key mounts and kept PEM/private-key
  material out of lifecycle evidence.
- Added issue, stage, overlap verification, activation, retirement, rollback,
  expiry warning/critical, expiry block, and revocation block behavior.
- Required the candidate certificate metadata version to match the admitted
  external TLS reference before activation.

## Decision

The current certificate is retained through the minimum verification overlap.
A failed candidate probe rolls back to the still-valid current certificate;
an expired or revoked current certificate blocks normal rotation. Emergency
recovery remains an operator-managed external TLS responsibility.

## Verification

This Slice uses deterministic certificate metadata only. It does not load a
certificate, private key, contact a TLS endpoint, or claim certificate
rotation in any external environment.

- Focused tests: `15 passed`; lifecycle module and runner statement/branch
  coverage `100%`.
- Platform Slice Gate: `340 passed, 6 skipped`; runner statement/branch
  coverage `100%`.
- Contract validation: `166` schemas, `228` examples, `196` negative examples,
  and `7` OpenAPI documents.
