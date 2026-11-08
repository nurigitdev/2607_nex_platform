# P8-S74: IA BUSINESS_FORMAL UX

## Status

Completed on 2026-10-23.

## Scope

The authenticated IA approval inbox now presents EOS-owned
`BUSINESS_FORMAL` work without merging it with `NSL_WRITE` or
`AGENT_FORMAL`. The existing approval routes, OA browser session boundary and
WC decision authority remain unchanged.

No database migration or new persistence structure was introduced.

## Safe Read Model

WC adds a display-safe `formal_approval` projection only to
`BUSINESS_FORMAL` gates:

```text
current stage / stage count
requested leadership role
opaque EOS stage target
OrgUnit and Project identifiers
terminal WC gate state
```

Stage progress is parsed only from the bounded EOS display-safe summary.
Legacy or malformed summaries retain a compatible projection with unknown
stage values. Protected operation references, resume targets, semantic hashes
and source references never enter the view.

The inbox, detail and standalone gate schemas require this projection for the
business-formal domain. AE API admits the additive field only for that domain
and fails closed on provider, target, progress, terminal-state or field-shape
drift.

## IA Experience

The existing approval workbench retains distinct domain badges and adds:

- stage and requested-role context in each business-formal inbox row;
- a stable progress indicator in the selected detail;
- current stage, total stages, EOS target, OrgUnit, Project and terminal state;
- terminal-state synchronization immediately after approve or reject;
- responsive one-column formal metadata on narrow viewports.

Anonymous users still see only the credential login shell. Approval routes
remain session protected, authorization is still refreshed through OA by WC,
and logout returns immediately to the login view.

## Protected Smoke

The S74 protected smoke uses all three actual test databases:

1. migrate and verify `nex_eos_test`, `nex_wc_test` and `nex_oa_test` with
   their service-local users;
2. create a two-stage EOS policy, organization, Project, committed
   BusinessOperation and ApprovalInstance;
3. resolve the `TEAM_LEAD` and project its active stage into WC;
4. add an NSL WRITE gate for explicit domain-separation evidence;
5. sign in through the actual OA credential/session routes;
6. inspect stage `1 / 2`, role, EOS target and pending state in AE Web;
7. approve through AE API and WC with fresh OA authorization;
8. verify the WC work item, immutable decision and outbox row;
9. verify EOS remains the stage lifecycle owner until its decision consumer
   advances the persisted active stage;
10. remove all scoped EOS, WC and OA rows and verify zero residue.

The Playwright evidence contains only counts and booleans. Credentials,
database URLs, service tokens and protected payload fields are rejected from
the evidence boundary.

## Verification

- Focused AE facade and WC approval regression: `80 passed`.
- Focused formal-boundary coverage regression: `57 passed`.
- Actual EOS/WC/OA PostgreSQL plus Playwright smoke: `1 passed`, no skip.
- AE Web Node regression: `359 passed`, no failure or skip.
- Contract validation: `188` schemas, `250` examples, `217` negative examples
  and `9` OpenAPI documents.
- AE API Slice Gate: PASS.
  - `5166 passed`, `37` protected skips.
  - statement coverage: `98.41%`.
  - branch coverage: `96.39%`.
  - `approval_facade.py`: statement/branch `100% / 100%`.
- WC approval scope: statement `98.76%`, branch `96.35%`.
- WC whole-service Slice Gate inventory: `474 passed`, `15` protected skips.
  Its pre-existing whole-service coverage debt remains below the unmodified
  `95% / 94%` thresholds at `94.28% / 91.88%`; this is improved from the
  previously documented `92.08% / 89.37%` baseline. Thresholds were not
  lowered and the failed whole-service gate was not represented as passing.

Remote generation, embedding and reranking providers were not required.

## Exit Decision

P8-S74 is closed. IA can now present and decide EOS formal approval work in
the shared approval inbox while preserving EOS lifecycle ownership, WC human
decision ownership, OA authorization ownership and NSL WRITE domain
separation. P8-S75 may perform the planned dual-approval separation
acceptance.
