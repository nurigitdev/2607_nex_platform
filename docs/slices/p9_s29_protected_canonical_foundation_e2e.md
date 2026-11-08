# P9-S29: Protected Canonical Foundation E2E

## Scope

P9-S29 promotes the earlier CA03 source-authority smoke into one canonical,
tenant-scoped protected journey. It uses the actual NeX-AE, NeX-WC, NeX-OA,
NeX-EOS, and NeX-WA PostgreSQL test databases and in-process HTTP service
surfaces protected by OA-signed RSA service tokens with exact audiences and
minimum scopes.

No remote model provider, Approval, WC Delegation, or NSL execution is part of
this foundation journey.

## Canonical Journey

The protected test proves all 29 planned outcomes:

1. current migrations and exact database identities for all five services
2. current WA API and consumer persistence startup
3. Human-owned `READY` Artifacts
4. PA AgentResult while required delivery is `PENDING`
5. pre-ACK AgentResult rejection
6. WC result delivery ACK and completed AgentExecution
7. signed AE AgentResult notification
8. signed AE Artifact notification
9. reference/hash-only WA intake
10. two concurrent PostgreSQL queue claims
11. signed AE source projection re-read
12. OA Human authority verification
13. EOS Project and historical membership verification
14. AgentResult `PRIMARY` evidence
15. WC result resolution by execution/claim lineage
16. WC result `SUPPORTING` evidence
17. one AgentExecution to one Agent WorkAsset
18. Human Artifact to `HUMAN_OWNED_ARTIFACT`
19. no Human effort inferred from ownership
20. duplicate notification semantic reuse
21. source hash conflict fail-closed
22. cross-tenant read fail-closed
23. no Approval authority in WA
24. no evidence Delegation authority in WA
25. no NSL execution in WA
26. basic/detail/audit privacy separation
27. missed Artifact notification recovered by bounded reconciliation, followed
    by idempotent delayed notification
28. no salary, MM, cost, or P/L authority in WA
29. zero owned test residue

The resulting aggregate contains four WorkEvidence rows, three WorkAsset rows,
three `PRIMARY` bindings, and one `SUPPORTING` binding. The delayed Artifact is
the only newly admitted reconciliation job; the two already-notified sources
are reused by semantic identity.

## Defects Closed

Actual PostgreSQL execution exposed two source-backed integration defects:

- a terminal single reconciliation page with both cursors `null` was rejected
  as cursor reuse; cursor equality is now checked only when `has_more=true`
- AE Artifact collection projection returned a bare SHA-256 digest while WA
  intake requires `sha256:<digest>`; collection output now emits the canonical
  hash reference used by the detail/intake boundary

Both defects have focused unit regressions. No schema migration or public API
field change was required.

## Protected Evidence

- actual database identities: `nex_ae_test`, `nex_wc_test`, `nex_oa_test`,
  `nex_eos_test`, `nex_wa_test`: `PASS`
- migrations current: `PASS`
- signed service trust and exact scopes: `PASS`
- concurrent claims: `2`, distinct jobs
- reconciliation: `2` reused, `1` admitted
- aggregate: `4` evidence, `3` assets
- privacy and cross-tenant denial: `PASS`
- zero owned residue: `PASS`
- protected E2E: `1 passed`
- focused regression: `89 passed`, `1` protected skip
- NeX-WA Slice Gate: `315 passed`, `12` protected skips
- statement coverage: `97.30%` against P9 floor `96%`
- branch coverage: `94.70%` against P9 floor `94%`
- contracts: `226` schemas, `290` examples, `244` negative examples, `10`
  OpenAPI documents
- remote provider: not required
- `git diff --check`: `PASS`

Only sanitized counts and decisions are recorded. Tokens, database URLs, raw
source bodies, Artifact bytes, prompts, and private content are excluded.
