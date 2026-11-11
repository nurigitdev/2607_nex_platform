# MyBee Phase 1 S1-05 D12 WorkCodeSet and BusinessReady Gate

## Scope

S1-05 admits the MB1-01 D12 catalog into EOS Project operations and adds a
business-readiness projection without changing the existing technical Project
lifecycle. It closes `SRS-PRJ-002`, `SRS-PRJ-003`, `SRS-PRJ-004`, and
`SRS-PRJ-008` for the Phase-1 boundary.

The canonical plan proposed migration `2519`, but that immutable number is
already occupied in the source-backed repository. S1-05 therefore uses the
next available additive migration,
`2524_eos_project_work_code_readiness`; no migration history was rewritten.

## Catalog Admission

EOS pins all of the following MB1-01 identities:

- catalog ID `mybee.fl.d12.project-governance`;
- catalog version `1.0.0`;
- catalog digest
  `sha256:31e5a24a8a5e62f80fc1571a4a232723a90f9c1b628841ae80df24654848c8ba`;
- mandatory codes `FL0012004`, `FL0012005`, `FL0012006`, `FL0012013`, and
  `FL0012026`;
- mandatory-code-set hash
  `sha256:f867477ed5983904e1c4a353bf05a4a11ffb56b5fa0299ffd63bbc8cd70bd9a1`.

Application and PostgreSQL constraints both fail closed when these identities
drift. Additional canonical FL codes may be present, but duplicate, malformed,
unsorted, or incomplete code arrays are rejected.

## Persistence Boundary

- `eos_project_work_code_set` stores immutable approved revision headers.
- `eos_project_work_code_entry` stores normalized, ordered code membership.
- One Project owns one revision stream; revision 1 starts it and later
  revisions advance exactly by one under a PostgreSQL advisory lock.
- Exact identity and semantic replay returns the existing revision.
- Identity drift, revision gaps, stream replacement, direct update, and direct
  delete fail closed.
- Human PM identity and Project Agent identity must be distinct. PA identity is
  represented by an opaque stable reference and evidence hash; an Agent
  registry is not invented in this Slice.

## BusinessReady Projection

The existing Project `ACTIVE` status remains a technical lifecycle state. It
does not grant MyBee business execution readiness.

`BUSINESS_READY` requires all of these current facts for the requested date:

1. technical Project status is `ACTIVE`;
2. one effective approved WorkCodeSet is pinned to the admitted catalog and
   contains the five mandatory D12 codes;
3. exactly one approved ProjectCompanyBinding is effective;
4. the designated PM has an active `MANAGER` membership;
5. at least one active Project member exists;
6. a distinct PA identity and its evidence hash are bound.

The read model returns deterministic reason codes and the intermediate states
`DRAFT_CONFIGURATION`, `WORK_SET_APPROVED`, `MEMBER_READY`, `BUSINESS_READY`,
or `BLOCKED`. `budget_bound_if_required` is `true` under the current policy
because S1-05 imposes no budget prerequisite; a later budget packet may make
that condition substantive without conflating it with technical `ACTIVE`.

## API and Trust

- `POST /internal/v2/projects/{project_id}/work-code-sets:approve`
  - operation `PROJECT.WORK_CODE_SET.APPROVE`;
  - requires signed `service:call`, fresh `project:work-code:approve` OA
    authority, active owner/manager membership, and an active designated PM;
  - reuses EOS BusinessOperation idempotency and canonical payload hashing.
- `GET /internal/v2/projects/{project_id}/work-code-set`
  - operation `PROJECT.WORK_CODE_SET.GET`;
  - requires signed trust plus fresh `project:work-code:read` authority and an
    active membership unless the caller has Project administrator scope.
- `GET /internal/v2/projects/{project_id}/business-readiness`
  - operation `PROJECT.BUSINESS_READINESS.GET`;
  - uses the same tenant, authority, and membership boundary.

The three canonical names are admitted by the shared operation registry and
the EOS OpenAPI digest is repinned in the MyBee exact compatibility lock.

## Deferred Scope

- WorkAssignment, performer allocation, Grade, and planned Man-Day belong to
  S1-06.
- Agent registry validation beyond the opaque PA identity evidence reference.
- Budget readiness, Project close, and P&L rules.
- NSL Skill/Tool authoring beyond the admitted canonical EOS API operations.

## Verification

- Focused runtime and API suite: `32 passed, 1 protected smoke skipped`.
- Actual `nex_eos_test` protected PostgreSQL and compatibility smoke:
  `41 passed`; migration `2524` was applied in an isolated schema, immutable
  revision persistence was verified, concurrent competing revision 3 writes
  produced exactly one commit and one conflict, and schema cleanup left zero
  residue.
- EOS/MyBee Slice Gate: `1198 passed, 34 protected tests skipped`; all `6/6`
  commands passed.
- Slice Gate coverage: statement `97.00%`, branch `96.09%`.
  - `project_work_codes.py`: statement `98.97%`, branch `98.21%`.
  - `project_business_api.py`: statement and branch `100.00%`.
- Contract validation passed for `233` schemas, `292` examples, `245`
  negative examples, and `10` OpenAPI documents.
- Golden Journey transition and demo/product dependency audits passed.
- Remote model providers are outside this deterministic EOS boundary and were
  not required.
