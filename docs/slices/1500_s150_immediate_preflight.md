# Slice 1500: S150 Immediate Preflight

Status: Complete.

## Outcome

- Composed existing S143/S144/S146/S147 protected boundaries through the S149
  Single-host acceptance instead of duplicating infrastructure probes.
- Added the actual `nex_ag_test` observability/restart smoke and deterministic
  mock incident-delivery rehearsal.
- Bound trust, five PostgreSQL databases, RustFS, three live provider
  capabilities, observability, and incident evidence to the exact S149 release
  candidate and release-set digest.
- Enforced the `IMMEDIATE_PREFLIGHT_4H` window, zero residue, metadata-only
  evidence, and deployment separation.
- Hardened S149 live aggregation so generation probes must explicitly report
  reasoning mode `disabled`.
- Kept external notification `EXTERNAL_NOT_ACTIVATED`; mock delivery is
  operational rehearsal, not a granted P1 waiver.
- OCI source admission accepts only committed documentation, smoke tooling, and
  test changes after the pinned image revision. Runtime-affecting changes,
  non-ancestor revisions, and tracked dirty worktrees still fail closed. This
  keeps the immutable release candidate stable while S150 assurance evidence is
  assembled.
