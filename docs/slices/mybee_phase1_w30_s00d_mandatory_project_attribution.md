# MyBee Phase 1 W30-S00D Mandatory Project Attribution

## Status

- Slice: `W30-S00D`
- Status: implemented and verified
- Design authority: `W30-CA02`
- EOS migration: `2533_eos_mandatory_project_attribution.sql`
- Remote model providers: not required

## Boundary Decision

Every new MyBee business proposal and its immutable document-signoff lineage
must carry an exact pair of internal Project UUID and user-facing approved
Project registration code. A Project request code cannot satisfy this
boundary. The Project must resolve to the same tenant and company and must be
`ACTIVE` at EOS admission.

The canonical attribution flow is:

```text
approved Project UUID + registration code
  -> MyBee business proposal v2
  -> EOS document-signoff context v2
  -> ApprovedDocumentEnvelope v2
  -> S3-01 Project-specific VoucherCandidate v2
```

User-facing proposal and approval projections expose Project registration
codes. UUIDs remain the internal relational keys and are never replaced by
business identifiers.

## Contract And Persistence

The MyBee business-proposal template and domain contract are versioned to v2.
The proposal contract rejects company-empty scope, request codes, malformed
codes, duplicate bindings, and UUID/code cardinality drift. Approval request
hashes bind the complete ordered Project UUID/code pair.

EOS migration 2533 adds `allowed_project_codes JSONB NOT NULL DEFAULT '[]'` to:

- `eos_document_signoff_context`;
- `eos_approved_document_envelope`.

The v2 context is admitted only when every code resolves to the exact active
Project UUID scope. Terminal approval materializes the immutable v2 envelope
with the same binding. Replay with changed IDs or codes fails closed and rolls
back both the scoped approval case and document context.

Existing v1 contexts, envelopes, and voucher rows remain readable and
unchanged. This Slice does not retrofit `eos_voucher_draft` or create the
VoucherCandidate schema. S3-01 owns the Project-specific VoucherCandidate v2
and must consume this immutable document attribution.

## Compatibility

- business proposal v1 template remains retained for historical evidence;
- v1 EOS document-signoff and approved-document projections remain exact when
  no Project codes are stored;
- OpenAPI admits both v1 and v2 schemas and requires Project codes for v2;
- migration inventory and compatibility lock digests were refreshed;
- the S3-01 migration reservation now resolves to the next available EOS
  version after inventory refresh.

## Verification

- Focused document and lifecycle suites: `116 passed, 2 skipped`.
- MyBee regression suite before final branch hardening: `300 passed`.
- Actual EOS/WC/OA PostgreSQL protected smoke: `1 passed`.
  - connected to `nex_eos_test`, `nex_wc_test`, and `nex_oa_test`;
  - applied EOS migrations through 2533 in an isolated schema;
  - admitted v2 Project attribution, completed WC approval, materialized the
    v2 envelope, verified replay, and removed all smoke residue.
- NeX-EOS Slice Gate: `1329 passed, 42 skipped`.
  - statement coverage: `96.24%`;
  - branch coverage: `94.05%`;
  - contract validation: passed;
  - Golden Journey transition audit: passed;
  - demo-to-product dependency audit: passed.

Machine-readable Gate evidence:

- `reports/quality/w30-s00d-eos.coverage.json`

## Next Entry

The W30 entry checkpoint may now verify S00A through S00D as one Project
application, approval, lifecycle, Project Agent synchronization, and mandatory
document-attribution baseline. S3-01 may then add Project-specific
VoucherCandidate v2 without weakening this UUID/code or approval-proof
boundary.
