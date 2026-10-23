# P8-S63: Golden A Seed / Fixture Baseline

## Status

Completed on 2026-10-23.

## Scope

- Added one canonical, semantic-hash-protected Golden A fixture manifest.
- Added reusable validation, seed, readback verification, residue counting, and
  reset support for OA and EOS.
- Seeded deterministic tenant, requester, approver, organization hierarchy,
  NVTProject, Mother Project, child Project, Account set, voucher-line policy,
  Agent/Skill admission reference, and approval target data.
- Bound the fixture to the admitted NSL v0.2 wheel lock and required public API
  symbols without activating the WRITE planning capability.
- Added fast SQLite/in-memory regression and an opt-in actual PostgreSQL
  protected smoke for `nex_oa_test` and `nex_eos_test`.

No database table, migration, public API field, remote model-provider call, or
authoritative business WRITE was added. Planning activation and LLM
candidate-only/ambiguity-stop behavior remain P8-S64 responsibilities.

## Canonical Baseline

The tracked manifest is
`scripts/smoke/data/p8_golden_a_fixture.v1.json`.

- fixture id: `p8-golden-a-voucher-draft-v1`
- fixture hash:
  `sha256:37b5296f414908080d44dbf788f88c7eca343881e315ad56b9529f1dd0f5839b`
- protected tenant: `p8-golden-a`
- requester: `employee-1001`
- approver: `employee-2001`
- NVTProject: `81000000-0000-4000-8000-000000000001`
- Mother Project: `82000000-0000-4000-8000-000000000002`
- child Project: `82000000-0000-4000-8000-000000000001`
- debit Account: `83000000-0000-4000-8000-000000000001`
- credit Account: `83000000-0000-4000-8000-000000000002`
- policy: `golden-a.travel.cash.v1`, version `1`
- business capability/tool: `FINANCE.CREATE_VOUCHER_DRAFT`
- admitted NSL Skill: `FINANCE.VOUCHER_DRAFT_CREATE`, version `1.0.0`
- Skill semantic hash:
  `sha256:908387dd8dc53697478e83594019e9bfa86e425bb04062f65fc49df4f6303dc5`
- activation state: `LOCKED_PENDING_P8_S64`

The project and account IDs match the existing Golden A EOS command example.
The deterministic policy maps `GENERAL + TRAVEL + CASH + effective date` to
the two stable Account references and the fixed `DEBIT`, `CREDIT` line order.
The fixture includes an exact project code and an empty attachment set, so no
display-name ranking or RustFS dependency is introduced.

## Safety Boundary

Fixture loading fails closed when any of the following occurs:

- semantic hash mismatch or non-canonical top-level structure;
- private credential-shaped fields;
- duplicate or broken organization, project, account, or principal references;
- requester/approver identity collision or unresolved approval assignment;
- scenario and voucher-line policy mismatch;
- inactive policy period, malformed amount, or non-empty baseline attachment;
- path escape, unreadable lock, wheel digest/version mismatch, or missing
  required NSL public symbol;
- premature activation before P8-S64.

The public seed projection contains stable IDs, hashes, policy, and activation
state only. It excludes the natural-language prompt and any private payload.

## Seed And Reset Semantics

The seeder reuses the existing OA tenant membership registry and EOS
organization, project, account, and approver-resolution repositories. After
persistence it reads back and verifies:

1. Mother and child Project depths are exactly `1` and `2`;
2. debit and credit Accounts are active for the scenario date;
3. the `HIGH` risk approval policy resolves the seeded `GROUP_LEAD` assignment
   to `employee-2001`;
4. a second clean seed produces the same public projection and approval
   resolution hash.

Reset is tenant-scoped to the dedicated `p8-golden-a` tenant and removes only
the OA/EOS fixture rows in foreign-key-safe order. The protected gate proves
zero residue after the final cleanup.

## Protected PostgreSQL Evidence

The opt-in gate used actual local PostgreSQL test databases and verified the
exact identities:

- `nex_oa_test` as `nex_oa_user`;
- `nex_eos_test` as `nex_eos_user`.

It ran both service migration runners, compared every tracked migration version
with `schema_migrations`, then executed:

```text
reset -> seed -> count/readback -> reset -> seed -> exact result comparison
      -> final reset -> zero residue
```

The first seed produced exactly one tenant, two subjects, two memberships, one
NVTProject, two Projects, two Accounts, four organization units, one position,
and one position assignment.

## Verification

- Focused fixture regression: `52 passed`, `1 skipped` protected test.
- New fixture module statement coverage: `100%`.
- New fixture module branch coverage: `100%`.
- Actual OA/EOS PostgreSQL protected smoke: `1 passed`, no skip.
- NeX-EOS Slice Gate: `378 passed`, `13 skipped` protected tests.
- Slice Gate statement coverage: `99.83%` against the `95%` threshold.
- Slice Gate branch coverage: `100.00%` against the `94%` threshold.
- Contract validation: 188 schemas, 250 examples, 217 negative examples, and
  9 OpenAPI documents.
- Ruff and Python compile checks: passed.
- Black formatting check: passed after formatting.

The PostgreSQL evidence was executed separately with
`NEX_P8_S63_GOLDEN_A_POSTGRES_GATE=1`; it is not inferred from the intentionally
skipped default regression run.

## Exit Decision

P8-S63 is ready to close. Golden A now has one deterministic, resettable,
source-controlled business-data baseline with actual OA/EOS PostgreSQL evidence
and an admitted NSL v0.2 lock boundary. P8-S64 may activate planning against
these exact references without inventing a second fixture or granting the LLM
authority over Project, Account, voucher-line, or approval binding.
