# CP-M1-E2E-FX-01B.7P: Installed D04 Controlled-Skill Initial Diagnostics and Contract Alignment

## Status

- Date: `2026-11-20`
- Status: `COMPLETE`
- Parent boundary: `CP-M1-E2E-FX-01B.7`
- Predecessor: `CP-M1-E2E-FX-01B.7O`
- Database migration: none
- Public API change: none
- Remote provider: required only for final exact-head replay

## Failure Reconciliation

The `.7O` exact-head replay completed D12 through the installed NSL v0.2
runtime and reached `READY_FOR_D04`. The D04 `CONTINUE_EXECUTION` RuntimeJob
then failed with `ae.product_controlled_skill_initial_failed`. That generic
error hides whether authority resolution, artifact admission, durable binding,
NSL execution construction, approval publication, or wait registration failed.

Source reconciliation also found a direct conflict with the `.7M` accounting
separation-of-duties decision. The D04 initial path requires the requester to
hold `finance:journal:approve`, although the admitted acceptance contract grants
the requester `finance:journal:request-approval` and reserves approval authority
for a distinct accounting approver.

The first exact-head replay after that authority correction exposed a second,
independent contract defect. The signed D04 Skill `1.0.0` had no `check`
statement. NSL v0.2 therefore completed its controlled prefix with validation
status `NO_CHECK`; the runtime correctly refused to publish an approval request
and persisted `ae.product_controlled_skill_approval_not_suspended`. This was a
Skill contract mismatch, not an approval-authority or publication failure.

The next protected replay admitted D04 Skill `1.0.1`, persisted the approval
request, consumed the approved generalized wait/event, and resumed the
controlled WRITE. It then failed with typed result `eos.write_not_committed`.
The EOS posting client and public schema require
`eos_journal_post_command.v1`, while M1 plan materialization and D04 `1.0.1`
still emitted and checked `eos.journal_posting_command.v1`. The command builder
therefore failed before the EOS posting HTTP request. No Journal mutation was
attempted.

## Decision

1. Preserve bounded stage-specific D04 initial failure codes across the P5
   executor boundary. Never persist provider bodies, unrestricted exception
   text, credentials, or prompt content.
2. Require the originating requester to have current
   `finance:journal:request-approval` authority when entering the D04 approval
   wait.
3. Preserve requester and approver as distinct principals. Self-approval is
   fail-closed.
4. On controlled-WRITE resume, revalidate both principals:
   - requester: current request-approval authority;
   - evidence-bound approver: current `finance:journal:approve` authority.
5. Keep the governed operation actor bound to the requester while including the
   evidence-bound accounting approver in typed authorization facts. The
   approval evidence remains the authority for the decision; role alone does
   not grant write authority.
6. Admit the existing runtime target role `finance_approver` for the accounting
   approver in installed acceptance in addition to the EOS leadership position
   `GROUP_LEAD`.
7. Reuse the existing Platform ApprovalEvidence, generalized wait/event,
   RuntimeJob, NSL binding, OA, WC, and EOS structures. Add no migration,
   scenario fixture, fixed identity, or tenant-specific fallback.
8. Do not weaken the NSL runtime to accept `NO_CHECK`. Publish D04 Skill
   `1.0.1` with deterministic checks for the admitted Journal command schema and
   positive VoucherCandidate version/revision before its approval statement.
9. Promote the corrected Skill through a new signed NSP, verification-only
   public key, Product Capability Registry, runtime admission, runtime
   activation, and Product coordinator activation. Preserve every v1 artifact
   unchanged as controlled rollback evidence.
10. Keep Skill and Tool contract versions independent. D04 Skill `1.0.2`
    continues to require the admitted Journal Tool contract `1.0.0`; the
    runtime resolves that version from the signed NSO `required_tools` record
    and fails closed unless exactly one matching WRITE Tool is present.
11. Use the EOS-owned `EOS_JOURNAL_POST_COMMAND_SCHEMA` constant when M1
    materializes D04 input. Publish D04 Skill `1.0.2` with the same canonical
    schema check. Do not add a dotted compatibility alias or mutate release v2.

## Implemented Boundary

- D04 `1.0.2` semantic hash:
  `sha256:54ed4365a9abb2646a8bc5ced81550fe6a27a9dbac363d925449a27198ee718c`.
- Signed release: `nex-mybee-m1-d04-d12-checkpoint-v3`; private signing key was
  not persisted, and only the Ed25519 verification key is packaged.
- Active immutable bindings:
  - Product Capability Registry `v4`, registry version `6`;
  - runtime admission `v4`;
  - runtime activation `v4`;
  - Product coordinator activation/rollback `v3`.
- Rollback is now bound to signed release v2, registry v3, and runtime
  admission v3. Active OCI contexts package current, immediate rollback, and
  historical v1 artifacts.
- The source-level controlled-prefix test executes the actual signed D04 Skill,
  proves `ALL_PASS`, and requires both checkpoint and approval request output.
- Installed authority composition no longer substitutes the Skill version for
  the Tool contract version; the distinct `1.0.2`/`1.0.0` pair is covered by a
  fail-closed regression test.
- M1 plan materialization imports the EOS-owned canonical schema constant, so
  planning, signed Skill validation, command construction, OpenAPI, and EOS
  posting admission share one schema identity.

## Verification

- Focused Product runtime, coordinator, planning, deployment, and historical
  compatibility regression: `451 passed, 1 skipped`.
- Active/rollback binding and Skill/Tool version reconciliation regression:
  `284 passed`.
- Product runtime deployment audit: `PASS`; no business fixture is used by the
  active runtime.
- D04 `1.0.2` release-chain and changed-path regression:
  `470 passed, 1 skipped`; the skip is the separately protected AE PostgreSQL
  smoke.
- AE Slice Gate: `PASS`; `6,896 passed, 53 skipped`, statement coverage
  `96.46%`, branch coverage `94.71%`, and all six contract/audit commands
  completed.
- First installed replay evidence: D04 approval request persisted and was
  approved/consumed; the prior suspension blocker is closed. The downstream
  schema mismatch was typed as `eos.write_not_committed`, and the isolated
  Compose/PostgreSQL run was cleaned without residue.
- Exact-head OCI evidence for Git revision `2f68c72e3d80`:
  - canonical nine-image release set: `PASS`, release-set digest
    `sha256:09b1ea91cd8383569f3acaf87b379d08921c48693606ce9ee914ab49a271d04d`;
  - AE product runtime image:
    `sha256:4acc4ece1ec27d8d913e93a5efb8eec079bfd350851d11a844dae30facd4a04d`;
  - packaged product admission proves signed release v3, Skill `1.0.2`, Tool
    `1.0.0`, immediate rollback to release v2, non-root execution, and no
    registry push or secret inclusion.
- Protected DGX preflight: `PASS`, `3/3` for Qwen3-Embedding-4B,
  Qwen3-Reranker-4B, and Qwen3.5-9B with immutable model revisions.
- Exact-head installed protected replay against eight isolated PostgreSQL
  schemas, OpenBao, RustFS, Compose, DGX, and Playwright proved:
  - three approval boundaries were created and consumed;
  - D12 `E1` and D04 `E2` both reached `SUCCEEDED`;
  - the VoucherCandidate reached `POSTED`;
  - immutable Journal `M1A7-2026-000001` was created with two lines;
  - the canonical command reached EOS rather than failing before HTTP
    execution.
- The replay was intentionally stopped after this Slice boundary because the
  completed steps did not advance to `RESULT_VERIFY` and IA AgentResult
  publication. That is a distinct downstream settlement/finalization boundary,
  not a D04 controlled-Skill admission or EOS posting failure.
- Cleanup evidence: every Compose container stopped and all eight isolated
  schemas were removed; AE and EOS residue queries returned no rows.
- Final AE Slice Gate: `PASS`, `6,896 passed`, `53 skipped`, statement
  `96.46%`, branch `94.71%`, and all six contract/audit commands passed.

## Exit Rule

The exit rule is satisfied. Focused regression and the AE Slice Gate pass; the
exact-head installed replay entered and consumed the D04 NSL approval wait with
separate requester and accounting approver authority; the controlled WRITE
posted an immutable EOS Journal; and the later result-finalization gap is
isolated as a distinct downstream boundary. All Compose and isolated
PostgreSQL state was removed after the protected run.
