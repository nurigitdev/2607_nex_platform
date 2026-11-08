# P9-S28: Contract / Negative / Drift Closure

## Scope

P9-S28 closes machine-readable drift across the NeX-WA intake and source
projection boundary. It changes no runtime business behavior, persistence
schema, or public payload. Existing fail-closed behavior remains authoritative.

The source caller boundary is now explicit in OpenAPI:

| Producer route owner | Required caller | Required scopes |
|---|---|---|
| NeX-WA evidence intake | `nex-ae-api` | `service:call`, `work:evidence:ingest` |
| NeX-AE AgentResult / Artifact sources | `nex-wa` | `service:call`, `work:source:read` |
| NeX-WC WorkResult sources | `nex-wa` | `service:call`, `work:source:read` |
| NeX-OA subject verification | `nex-wa` | `service:call`, `identity:subject:verify` |
| NeX-EOS project verification | `nex-wa` | `service:call`, `project:verify` |

Consumer constants, producer constants, OpenAPI extensions, canonical JSON
Schema links, positive examples, and negative examples are tested together.

## Negative Closure Matrix

The regression inventory proves all 18 canonical failures:

1. unsupported source
2. source hash mismatch
3. same identity with a different hash
4. cross-tenant access
5. unknown or inactive Human
6. CA/PA/EA without Project or Claim
7. IA Project spoof
8. Artifact not `READY`
9. Artifact version mismatch
10. WC lineage mismatch
11. pre-ACK AgentResult
12. duplicate logical Agent work
13. stale-worker settlement
14. raw/private payload admission
15. wrong intake scope
16. basic reader requesting detail
17. non-WA source projection caller
18. unknown autonomous authority profile

Three schema-negative fixtures were added to prevent raw AgentResult,
rendered Artifact bytes, and raw WorkResult payloads from entering the WA
projection contract. The test matrix also verifies that every behavioral
scenario remains backed by a named regression test, preventing silent test
inventory drift.

## Verification

- producer/consumer contract regression: `98 passed`
- NeX-WA Slice Gate: `314 passed`, `12` protected skips
- statement coverage: `97.17%` against P9 floor `96%`
- branch coverage: `94.49%` against P9 floor `94%`
- contracts: `226` schemas, `290` examples, `244` negative examples, `10`
  OpenAPI documents
- database migration: not required
- PostgreSQL smoke: not required; P9-S28 changes only machine-readable
  contracts and regression evidence
- remote model provider: not required
- `git diff --check`: `PASS`
