# CP-M1-E2E-FX-01B.1 Contract and Source Boundary Freeze

## Status

- Date: `2026-11-16`
- Status: `CLOSED`
- Parent work order:
  `NeX_MyBee_CP_M1_E2E_FX_01B_Durable_Business_Context_and_M1_Transaction_Orchestration_Closure_v1.0.md`
- Entry commit: `99f98138`
- Database migration: none
- Runtime activation: none
- Remote provider: not required
- Next Slice: `CP-M1-E2E-FX-01B.2`

This Slice admits the successor business-context contracts and freezes their
source, persistence, and activation boundaries. It intentionally does not
change the installed WorkIntent, delegation, claimed-planning, or execution
runtime.

## Contract Admission

The following strict JSON contracts were added:

- `ae.business_request_context.v1`
- `WorkIntent v1.2`
- `DelegationSpec v1.2`
- `p7.claimed_work_planning_source.v2`

Positive examples bind one exact normalized business request across all four
contracts. The admitted example has these immutable semantic identities:

- business context hash:
  `sha256:d3c0a333aa6cb70feafc1a7a9d6ac33be1814fc1161323f6f2d3169cdc44c6ff`
- WorkIntent semantic hash:
  `sha256:c8bf6ecfe189a887bb35c44ff5a008694f3853962f5cc9ca22fd01283b0c2c77`

The context carries normalized user input and source/model provenance only.
Unknown fields, duplicated raw prompt text, and model-supplied authority are
rejected by structure. Tenant, requester, Project UUID, OA decisions, account
identity, FX and period authority, approval proof, Candidate identity, and
Posting results remain owner-service facts.

## Compatibility Freeze

The machine-readable boundary manifest is
`domains/mybee/config/m1_transaction_orchestration_boundary.v1.json`.
It freezes these activation decisions:

| Contract | Installed runtime | Admitted successor | Activation |
| --- | --- | --- | --- |
| WorkIntent | `1.1` | `1.2` | `01B.2` |
| DelegationSpec | `1.0`, `1.1` | `1.2` | `01B.3` |
| Claimed planning source | `p7...v1` | `p7...v2` | `01B.3` |

Regression tests prove that the installed validators still reject the
successor versions and that the existing claimed planning source remains v1.
No legacy record is silently upgraded.

## Frozen Boundaries

The manifest records the seven installed source boundaries from public intake
through runtime composition and the existing JSON persistence authorities:

- AE WorkIntent JSON;
- WC WorkItem/delegation JSON;
- AE claimed-planning-source JSON;
- AE executable-plan JSON; and
- redacted result/evidence references.

It also records the exact eight M1 operations and their current
`ACTIVE_SIGNED_SKILL` or `CONTRACT_ONLY` state. No additional operation,
adapter, Tool, or Skill was activated.

Static guards cover raw-prompt duplication, model authority, fixed business
values, Golden A fallback, runner direct SQL, runner-owned product transitions,
and unsigned Skill substitution.

## Contract Validator Hardening

Repository contract validation now builds an in-memory JSON Schema registry
from local `$id` values. Cross-schema references therefore resolve
deterministically without network access. Registry construction and resolution
fail closed, while direct standalone schema validation remains compatible.

## WC Gate Ownership Reconciliation

The first standard WC Slice Gate ran all selected tests successfully but
reported statement `93.28%` and branch `90.94%`. Investigation showed that two
existing WC product-boundary suites were outside the filename patterns:

- `test_gb2_ca00_s20a_active_runtime_branches.py`
- `test_gb2_ca00_s20c_wc_durable_boundaries.py`

They are now explicit WC-owned tests, matching the existing AE ownership
mechanism. This is a Gate-selection correction, not a threshold reduction or
new product behavior. The standard WC command now reproduces the passing
coverage baseline without extra command-line arguments.

## Verification

- Focused contract, validator, and compatibility regression:
  `132 passed, 1 warning`
- Gate ownership and contract unit regression after reconciliation:
  `75 passed`
- Contract validation:
  `269 schemas`, `319 examples`, `260 negative examples`, `10 OpenAPI`
- AE Slice Gate:
  `6244 passed`, `46 skipped`, statement `96.45%`, branch `94.66%`
- AE product ownership coverage:
  statement `97.13%`, branch `94.98%`
- WC Slice Gate:
  `632 passed`, `21 skipped`, statement `98.44%`, branch `96.40%`
- Golden Journey transition audit: pass
- Demo/product dependency audit: pass
- `git diff --check`: pass

The protected skips are pre-existing opt-in PostgreSQL, RustFS, Playwright, and
live-provider suites. This contract-only Slice authorizes none of them. The
planned AE/WC PostgreSQL smoke and Checkpoint Gate remain after `01B.3`.

## Closure Decision

`CP-M1-E2E-FX-01B.1` is closed. Successor contracts are admitted and locally
resolvable, the current runtime is unchanged, no migration or provider access
was introduced, and implementation may proceed to durable WorkIntent business
context admission in `CP-M1-E2E-FX-01B.2`.
