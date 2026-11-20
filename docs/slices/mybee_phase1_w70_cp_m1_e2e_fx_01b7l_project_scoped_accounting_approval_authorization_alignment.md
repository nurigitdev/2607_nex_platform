# CP-M1-E2E-FX-01B.7L: Project-Scoped Accounting Approval Authorization Contract Alignment

## Status

- Date: `2026-11-20`
- Status: `SOURCE, CONTRACT, POSTGRESQL, AND SLICE GATES VERIFIED`; exact-head
  installed replay in progress
- Parent boundary: `CP-M1-E2E-FX-01B.7`
- Database migration: none
- Remote provider: not required for the corrective Slice Gates

## Live Failure Reconciliation

The `.7K` exact-head journey admitted the canonical VoucherCandidate validation
projection and advanced Product preparation to `WAITING_ACCOUNTING_APPROVAL`.
EOS created the second `ACCOUNTING_POSTING` WC approval item, but the approver
inbox did not expose it.

Source and runtime evidence identified a contract mismatch:

- EOS published its internal Project UUID as `target_project_scope_ref`;
- WC correctly required an exact match against OA `project_scope_refs`;
- OA effective authorization did not publish `project_scope_refs` even though
  `oa_project_grant` already owned Project Code grants.

## Decision

1. Keep internal EOS foreign keys and lineage on Project UUIDs.
2. Use the stable, user-facing Project Code as the cross-service authorization
   scope reference.
3. Resolve EOS UUID-to-Code from the authoritative `eos_project` row when an
   accounting approval WorkItem is projected. Do not persist a duplicate code
   in scoped approval bindings.
4. Publish sorted active Project Codes from OA effective authorization as
   `project_scope_refs`.
5. Include Project grant status, Project status, source version, and event hash
   in the effective authorization revision hash.
6. Keep WC target matching strict and case-sensitive. UUID fallback, implicit
   tenant dictionaries, and allow-on-missing behavior are prohibited.
7. Bind `target_project_scope_ref` into the EOS WorkItem semantic hash.

`ACTIVE` and `CLOSING` Project grants remain visible because closing activity
still requires controlled accounting work. `INACTIVE`, `CLOSED`, and revoked
grants are excluded.

## Implementation

- OA Project grant repositories now support subject-scoped authoritative
  listing for both in-memory and PostgreSQL profiles.
- OA effective authorization v1 now includes `project_scope_refs` and
  `project_scope_count`; canonical schema, examples, and negative privacy
  fixtures were updated together.
- EOS resolves Project Code at initial and subsequent accounting approval
  stages without changing persisted scoped approval schemas.
- Accounting approval decision replay reconstructs the same Project Code target
  before accepting WC lineage.
- WC's existing exact target compatibility logic remains unchanged.
- The installed Playwright journey now advances a completed approval through
  the product UI's `다음 요청 검토` action, or explicitly refreshes the inbox
  before selecting a newly published gate. Clicking an already-active route is
  not treated as an inbox refresh.

## Verification

- Ruff format/lint and Python compile: `PASS`
- focused OA/EOS/WC authorization regression: `141 passed`, `2` protected
  skips
- expanded approval, entitlement, and contract regression: `308 passed`, `6`
  protected skips
- canonical OA contract runner: `PASS`
- contract/OpenAPI regression: `59 passed`
- actual PostgreSQL protected smoke: `2 passed`
  - `nex_oa_test`: migration, subject grant restart query, authorization
    decision, and zero-residue cleanup;
  - `nex_eos_test`: Project Code approval target, multi-stage replay,
    immutable evidence, and zero-residue cleanup.
- OA Slice Gate: `PASS`
  - tests: `1259 passed`, `14 skipped`;
  - statement coverage: `96.69%`;
  - branch coverage: `95.11%`;
  - commands: `5/5`.
- EOS Slice Gate: `PASS`
  - tests: `2315 passed`, `67 skipped`;
  - statement coverage: `96.80%`;
  - branch coverage: `94.82%`;
  - commands: `5/5`.
- WC Slice Gate: `PASS`
  - tests: `747 passed`, `27 skipped`;
  - statement coverage: `97.66%`;
  - branch coverage: `95.16%`;
  - commands: `5/5`.
- exact-head DGX provider preflight: `PASS`, `3/3`
  - `Qwen3-Embedding-4B`;
  - `Qwen3-Reranker-4B`;
  - `Qwen3.5-9B`.
- first exact-head installed replay after the authority correction:
  - eight actual PostgreSQL databases and `210` isolated migrations admitted;
  - EOS advanced to `ACCOUNTING_POSTING:PENDING`;
  - WC returned the new accounting approval to the approver inbox
    (`pending_gate_count=1`), proving the Project Code authorization alignment;
  - the replay then failed because the browser harness remained on the
    completed first approval without invoking the UI's next-request refresh;
  - all eight isolated schemas were removed (`zero_residue=true`).
- AE Web M1 harness focused regression: `13 passed`.
- AE Web Node regression: `388 passed`.

## Exact-Head Replay Rule

The installed journey must prove that the approver's OA effective
authorization contains the canonical Project Code, the EOS accounting approval
WorkItem carries the same code, WC exposes the second approval, and Product
execution advances beyond `WAITING_ACCOUNTING_APPROVAL`. Any later failure is a
separate typed boundary and must not weaken this exact-match contract.
