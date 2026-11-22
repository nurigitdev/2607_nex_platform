# MyBee Phase 1 W30-S00 Scoped Document Signoff Finalization

## Status

- Slice: `W30-S00`
- Status: implemented and verified
- Dependencies: `S2-01`, `S2-02`, `MB2-01`, `W30-CA01`
- Runtime entry: W30 document-signoff prerequisite closed
- Remote model providers: not required

## Boundary

W30-S00 closes the production path from a scoped `DOCUMENT_SIGNOFF` request
through WC Human approval to one immutable EOS
`ApprovedDocumentEnvelope`. The existing `ACCOUNTING_POSTING` finalizer and
its accounting evidence remain separate and unchanged. An accounting proof
cannot satisfy document signoff, and document evidence cannot satisfy
accounting posting.

The MyBee adapter now sends the complete materialization context with the
request. EOS persists that context atomically with the scoped approval case
before WC publication. The context binds the exact Company, Project or
Project-set scope, document revision and hashes, amount/currency, validity
period, WorkCode and deterministic envelope identity.

EOS owns the immutable Project scope. OA supplies fresh Human identity,
`approval:decide` scope, policy-stage role, Company scope and authorization
revision. No synthetic Project or OA project grant is introduced.

## Persistence

Migration `2530_eos_document_signoff_finalization.sql` adds:

- `eos_document_signoff_context`, the immutable pre-decision materialization
  input bound to a scoped approval case;
- `eos_document_signoff_evidence`, the immutable final WC/OA decision proof;
- a nullable `scoped_document_evidence_id` proof source on
  `eos_approved_document_envelope`.

The envelope check constraint requires exactly one proof source: the existing
generic `business_approval_proof_id` or the new scoped document evidence.
Existing S2-01 rows and the public read projection remain compatible. The
context and evidence tables reject update and delete in PostgreSQL.

The MyBee source manifest now records `2530` as the current EOS migration
head. The W30-CA01 decision artifacts retain their `2529` source snapshot as
historical entry evidence.

## Finalization

The purpose-aware decision router preserves `ACCOUNTING_POSTING` and sends
only `DOCUMENT_SIGNOFF` to the dedicated finalizer. The finalizer:

1. admits the exact WC delivery and persisted work-item semantics;
2. reloads and locks the scoped case, Project bindings and context;
3. requires a fresh OA Human authorization, role, scope and Company match;
4. rejects requester/approver SoD violations, stale stages, expiry and drift;
5. advances a non-final stage and republishes the next WC work item;
6. creates no evidence or envelope for a rejected decision;
7. creates one evidence row and one envelope on final approval;
8. returns the original identities on exact replay and rejects changed replay.

No VoucherCandidate or PostedJournal is created by this Slice.

## Verification

- Focused W30-S00 regression: `54 passed`, `1 protected test skipped`.
- Focused finalizer coverage: statement `98.22%`, branch `97.96%`.
- Related source-manifest and W30 consistency regression: `63 passed`,
  `1 protected test skipped`.
- Actual EOS/WC/OA PostgreSQL protected smoke: `1 passed`, `54 deselected`.
  - connected to `nex_eos_test`, `nex_wc_test` and `nex_oa_test`;
  - applied current migrations in isolated schemas, including EOS `2530`;
  - used actual OA membership/authorization and an actual WC decision;
  - verified exact finalization/replay and immutable context/evidence guards;
  - dropped all isolated schemas after verification (zero residue).
- NeX-EOS Slice Gate: `1252 passed`, `40 skipped`; statement `97.02%`,
  branch `96.07%`; all `6/6` commands passed.
- Repository Checkpoint Gate: `20494 passed`, `150 skipped`; statement
  `98.64%`, branch `97.30%`; all `6/6` commands passed.
- Contract validation: `233` schemas, `292` examples, `245` negative examples
  and `10` OpenAPI documents passed.
- Golden Journey transition and demo/product dependency audits: passed.

Machine-readable gate evidence:

- `reports/quality/slice-nex-eos.coverage.json`
- `reports/quality/slice-latest.json`
- `reports/quality/checkpoint.coverage.json`
- `reports/quality/checkpoint-latest.json`

## Next Entry

W30 may proceed to `S3-01: VoucherCandidate v2 Immutable Revision/Line` using
migration `2531`. S3-01 must consume this admitted document-signoff lineage
and must not replace it with fixtures, direct database writes or an accounting
proof shortcut.
