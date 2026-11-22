# MyBee Phase 1 S2-01 ApprovedDocumentEnvelope

## Scope

S2-01 closes `SRS-DOC-001`, `SRS-DOC-002`, and `SRS-DOC-007` for the
approved business document boundary. EOS now seals an exact document revision,
attachment manifest, company and Project scope, currency allowance, validity,
and approval policy into an immutable envelope backed by a final
`BUSINESS_FORMAL` proof.

The Slice does not create another approval workflow. WC remains the Human
workflow owner, OA remains the current authorization owner, and EOS consumes
the final approval proof already produced by the existing EOS approval engine.

## Persistence Boundary

- Migration `2526_eos_approved_document_envelope` adds the single
  `eos_approved_document_envelope` table.
- A final proof can back only one envelope, and a document identity plus
  revision can have only one immutable semantic payload.
- The proof payload hash must equal the canonical hash of company, document
  revision, content and attachment hashes, scope, allowance, and validity.
- The proof must come from the `APPROVE_BUSINESS_DOCUMENT` protected operation,
  an approved EOS instance, an OA-authorized Human approval decision, and the
  exact policy hash/version.
- `PROJECT` and `PROJECT_SET` scopes require active Projects with effective
  company bindings. `COMPANY` scope carries no synthetic Project identifier.
- Material fields cannot be updated or deleted in PostgreSQL. A material
  change requires a new document revision and fresh business proof. Controlled
  lifecycle state transition from `ACTIVE` to `REVOKED`, `EXPIRED`, or
  `SUPERSEDED` remains possible for later lifecycle work.

## API and Consumer Boundary

- `GET /internal/v2/finance/approved-documents/{envelope_id}` exposes
  `BUSINESS.DOCUMENT_APPROVED.GET` only.
- Signed `service:call`, exact tenant identity, and fresh OA
  `finance:document:read` authority are required.
- No public create/approve route exists, so callers cannot bypass WC Human
  approval or manufacture proof references.
- MyBee validates the exact response field set, tenant/envelope identity,
  hashes, Project-set shape, allowance, validity, and usability state.
- Expired envelopes remain auditable but are returned with `state=EXPIRED` and
  `usable=false`.

`remaining_amount` equals `approved_amount` in S2-01 because consumption does
not yet exist. S2-04 owns committed consumption, duplicate source protection,
row locking, and remaining-allowance calculation inside the posting unit of
work.

## Compatibility

- Existing approval instance, decision, proof, policy, LegalEntity, Project,
  and ProjectCompanyBinding tables are reused.
- Existing v1 voucher drafts and Golden A behavior are unchanged.
- The EOS OpenAPI and MyBee compatibility lock advance together.
- No remote generation, embedding, or reranker provider is required.

## Verification

- Focused unit, API, contract, and persistence suite passed: `35 passed`,
  `1 skipped` when the protected PostgreSQL profile was disabled.
- Focused coverage for `approved_documents`, `approved_document_api`, and the
  MyBee consumer contract reached `99%` total coverage with no partially
  covered branches. The MyBee consumer and EOS API modules each reached
  `100%` statement and branch coverage.
- Actual `nex_eos_test` PostgreSQL smoke applied all migrations in an isolated
  schema, created a real final approval proof and envelope, rejected semantic
  update/delete, admitted a lifecycle state transition, and removed the schema.
  The protected run completed with `36 passed` and no skip.
- The NeX-EOS Slice Gate completed with `1087 passed`, `36 skipped`, statement
  coverage `96.96%`, and branch coverage `96.11%`. The scoped MyBee consumer
  contract measured `100%` statement and branch coverage.
- Contract validation passed with `233` schemas, `292` examples, `245`
  negative examples, and `10` OpenAPI documents. Golden-journey transition and
  demo/product dependency audits also passed.
- Machine-readable gate evidence is stored at
  `reports/quality/mybee-s2-01-nex-eos.coverage.json`.
