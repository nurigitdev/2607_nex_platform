# Slice 1430: Platform Production Security Local Rehearsal

## Outcome

- Added an opt-in protected local rehearsal using 32 mode-`0600` temporary
  secret files across two generations.
- Started five candidate-generation owner child processes and five
  reverse-order previous-generation rollback child processes with isolated
  process environments.
- Generated local current and candidate certificates, performed real HTTPS
  probes against current, candidate, and restored-current endpoints, and kept
  server private keys inside the temporary managed-termination adapter.
- Verified zero temporary file residue and emitted metadata/count evidence
  only.

## Boundary

This is actual local process and TLS execution, not an external secret-manager
or managed-TLS acceptance. It must be enabled with
`NEX_S143_LOCAL_SECURITY_REHEARSAL=1` and `NEX_PROFILE=test`. Production and
external environments remain blocked pending Slice 1431.

## Verification

- Protected execution: `PASS`; five candidate owner processes, five rollback
  owner processes, three HTTPS probes, and zero temporary residue.
- Focused tests: 7 passed; statement coverage 100%, branch coverage 100%.
- Platform Slice Gate: 334 passed, 6 protected tests skipped as designed;
  100% statement and branch coverage for the Slice runner.
- Contract validation: 166 schemas, 228 examples, 196 negative examples, and
  7 OpenAPI documents passed.
- Evidence serialization was compared with every materialized current and
  candidate secret value; no private value was present.
