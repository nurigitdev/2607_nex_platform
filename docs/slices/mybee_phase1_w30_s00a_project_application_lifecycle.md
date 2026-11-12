# MyBee Phase 1 W30-S00A Project Application Lifecycle Foundation

## Status

- Slice: `W30-S00A`
- Status: implemented and verified
- Design authority: `W30-CA02`
- EOS migration: `2531_eos_project_application_lifecycle.sql`
- Remote model providers: not required

## Boundary

W30-S00A establishes EOS ownership of Project applications, annual business
code allocation, exact business-code resolution, and the admitted Project
lifecycle. Internal UUIDs remain technical identities. Request and
registration codes are the identities exposed to users and IA/NSL inputs.

This Slice admits only the following product mutations:

```text
DRAFT create -> DRAFT revise -> SUBMITTED
```

Final WC committee approval or rejection, ACTIVE Project materialization, and
retirement of the direct-create product path remain owned by W30-S00B. S00A
provides an in-session registration-code allocator so S00B can allocate the
code and insert the approved Project in one EOS transaction without an
intermediate commit.

## Persistence

Migration 2531 adds:

- `eos_project_code_counter`, keyed by tenant, code kind, purpose, and year;
- `eos_project_application`, the authoritative DRAFT/SUBMITTED decision input;
- `eos_project_app_revision`, an immutable semantic-hash-bound revision log;
- Project application lineage, purpose, origin, approval evidence, and PA sync
  state on `eos_project`;
- PostgreSQL guards for immutable revisions, application state/version changes,
  immutable Project business identity, and the exact Project lifecycle matrix.

Code years use `Asia/Seoul`. A new annual key starts at `0001`; no destructive
reset job exists. PostgreSQL atomic upsert prevents duplicate allocation, and
`9999` overflow fails closed. Request codes use `<TENANT4>R<YY><NNNN>` and
registration codes use `<TENANT4><PURPOSE><YY><NNNN>`.

Existing Projects remain `LEGACY_DIRECT`. No synthetic request code is
backfilled. Application-created Projects must use `APPROVED_APPLICATION` and
carry valid request, registration, and approval-evidence lineage.

## Runtime And Contract

The EOS runtime now provides signed internal contracts for:

- `PROJECT.APPLICATION.CREATE`
- `PROJECT.APPLICATION.REVISE`
- `PROJECT.APPLICATION.SUBMIT`
- `PROJECT.APPLICATION.GET`
- `PROJECT.PROJECT.RESOLVE`

Fresh OA authorization is required for every operation. Applicant ownership is
enforced for mutation, while a separate admin scope permits controlled reads.
The exact Project resolver is tenant-scoped and redacts Project, parent, and
NVT UUIDs from its projection.

The persisted Project transition matrix is:

```text
ACTIVE   -> INACTIVE | CLOSING
INACTIVE -> ACTIVE
CLOSING  -> ACTIVE | CLOSED
CLOSED   -> terminal
```

All unlisted transitions and optimistic-version conflicts fail closed.

## Verification

- Focused S00A and related Project regression: `131 passed`, `1 protected
  smoke skipped` before the protected run.
- Contract/OpenAPI hygiene: `65 passed`, `1 protected smoke skipped`.
- Actual `nex_eos_test` protected run: `10 passed`.
  - verified database identity as `nex_eos_test` / `nex_eos_user`;
  - applied all EOS migrations through 2531 in an isolated schema;
  - issued 32 request codes concurrently through 8 workers;
  - observed unique and monotonic `VO00R260001..VO00R260032` codes;
  - dropped the isolated schema and verified zero residue.
- NeX-EOS Slice Gate: `1261 passed`, `41 protected tests skipped`.
- Slice Gate statement coverage: `96.70%` with `95.00%` required.
- Slice Gate branch coverage: `95.18%` with `94.00%` required.
- Contract validation: `233` schemas, `292` examples, `245` negative examples,
  and `10` OpenAPI documents passed.
- Golden Journey transition and demo/product dependency audits: passed.

Machine-readable Gate evidence:

- `reports/quality/slice-nex-eos.coverage.json`
- `reports/quality/slice-latest.json`

## Next Entry

W30-S00B may implement WC committee finalization using the S00A in-session
registration-code allocator. It must create the final approval evidence,
registration code, ACTIVE Project, application decision, and lifecycle outbox
atomically. It must not expose direct Project creation as a MyBee product path.
