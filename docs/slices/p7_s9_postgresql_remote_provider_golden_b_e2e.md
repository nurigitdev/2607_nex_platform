# P7-S9: PostgreSQL + Remote Provider Golden B E2E

## Status

Completed on 2026-10-19. P7 is closed and P8 entry is authorized.

## Goal

Close P7 with one protected Golden B journey across the actual AE, WC, and OA
test databases, live MO generation, admitted NSL READ execution, WC result
publication, parent resume, deterministic report finalization, restart-safe
replay, and zero owned residue.

## Source Audit and Changes

- Reused the P7-S7 live semantic admission and background runtime instead of
  adding another planner, queue, or worker.
- Injected the actual OA authorization API into claim and WorkResult submission
  boundaries. The smoke bootstraps one test membership and reads effective
  authorization twice.
- Added an optional parent completion verifier to the S7 composition boundary.
  S9 uses it to consume the existing `RESUME_EXECUTION` job, run the existing
  deterministic report executor, and finalize the parent AgentResult.
- Preserved `reconciliation_id` and all P7 semantic identities. WorkItem and
  WorkResult evidence is exported only as `sha256:` references.
- Recomputed the S5 fixture step and plan hashes after its deliberate
  `WC_DELEGATE_WORK` mutation. Canonical validation now sees the same semantic
  content that the fixture persists.
- Promoted claim generation, prompt binding versions, and hash-safe parent
  completion lineage into the final protected evidence.
- Updated the historical S141 production-responsibility closure guard from the
  pre-WC five-database baseline to the current six service database owners and
  seven responsibility owners. The responsibility audit itself already
  enforced those current values.

The original P7-S9 Slice introduced no new table or migration. P7-CA02 later
added the additive `1003_wc_work_item_authorization` migration and reran this
same Golden B journey without changing its execution topology.

## Protected Acceptance

The protected runner requires explicit activation, exact `_test` database
roles/targets, the admitted NSL source revision, and complete live-provider
configuration. It fails closed before mutation for any missing prerequisite.

```text
AE database / role       = nex_ae_test / nex_ae_user
WC database / role       = nex_wc_test / nex_wc_user
OA database / role       = nex_oa_test / nex_oa_user
AE migration head        = 2405_ae_claimed_planning_source
WC migration head        = 1003_wc_work_item_authorization
OA migration head        = 1376_oa_trace_projection_index
generation model         = Qwen3.5-4B
semantic stages          = INTENT, CONTEXT, PLAN
NSL source revision      = 3b4cb198888570a857e6fb0d3aa077930bb23504
claim generation         = 1
OA bootstrap/read calls  = 1 / 3
OA authorization gates   = work:delegate / work:claim / work:result:submit
checks                    = 51 / 51
owned residue             = 0
```

The generated background plan contains `LOCAL_SKILL` followed by
`DETERMINISTIC_REPORT`. The parent plan resumes from exactly one WC result and
then completes its own deterministic report. Replaying publication and parent
finalization returns the committed state without a second result.

The CA02 rerun preserves 51/51 checks while adding the create-time
`work:delegate` gate to the existing claim and result-submit checks. Sanitized
evidence is stored in
`reports/live/p7-s9-postgres-live-golden-b.json`.

## Verification

- S9 unit and protected live test: `16 passed`; statement `100%`; branch
  `100%`.
- P7 regression inventory: `214 passed`, `8 skipped` protected tests.
- Actual P7-S8 recovery smoke: `26/26`, zero residue.
- AE Slice Gate: `4,513 passed`, `16 skipped`; statement `98.29%`; branch
  `96.14%`.
- Authoritative WC/P7 Gate: `181 passed`; statement `96.74%`; branch `94.12%`.
- Contract validation: 174 schemas, 236 examples, 204 negative examples, and
  8 OpenAPI documents.
- P7-CA02 Repository Full Gate: `15,407 passed`, `48 skipped`; statement
  `96.83%`; branch `96.22%`.

The Full Gate initially exposed only a stale S141 hardcoded five-database
expectation after WC became the sixth service database owner. The current
responsibility matrix remained PASS. The closure guard was aligned with that
source-backed matrix, its focused regression passed, and the Full Gate was
rerun on the final change set.

## Privacy and Cleanup

Evidence excludes credentials, endpoint values, raw prompts, candidate
payloads, provider output, hidden reasoning, and private NSL result content.
AE, WC, and OA rows owned by the generated tenant are deleted after both
success and failure paths; the accepted run reported zero residue.
