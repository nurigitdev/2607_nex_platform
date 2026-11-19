# CP-M1-E2E-FX-01B.7D-A: Semantic Submit Budget and Zero-Residue Failure Closure

## Purpose

The `.7D` protected journey proved that approval/result progress diagnostics
were bounded and redacted, but both 60-second and 120-second generic action
budgets expired while transaction one was still performing synchronous
semantic planning. The admitted Qwen3.5-9B profile is expected to require
50-55 seconds per generation call, and the INTENT, CONTEXT, and PLAN stages
perform three sequential calls. A semantic submit therefore needs its own
budget rather than inflating every browser action.

The audit also found three historical isolated-schema sets from runs at 10:22,
10:44, and 11:13 KST. The later `.7D` runs at 14:07 and 14:13 left no new
schema, but the failure report did not expose cleanup evidence and the older
residue had never been reconciled.

## Decision

- Keep ordinary UI actions bounded at 60 seconds.
- Admit a dedicated 180-second semantic submit budget.
- Keep each transaction's approval/result budget at 900 seconds.
- Set the parent process budget to two semantic-submit/result windows plus a
  180-second startup and teardown margin: 2,340 seconds.
- Preserve the original live failure while attaching structured database
  isolation and cleanup evidence.
- Continue cleanup across all database owners when one owner fails, recording
  only bounded service IDs and exception type names.
- Fail closed when cleanup does not reach zero residue.
- Do not change product runtime behavior, database schema, public API, or
  provider output contracts.

## Implementation

- The Playwright harness accepts
  `NEX_MYBEE_M1_GOLDEN_SEMANTIC_SUBMIT_TIMEOUT_MS` independently from action
  and result timeouts.
- Prompt submission uses only the semantic submit budget. Login, navigation,
  approval controls, and logout continue to use the ordinary action budget.
- The Python runner derives its parent budget from the two semantic submit and
  result windows.
- `M1ProductGoldenJourneyExecutionError` carries redacted cleanup evidence into
  the final failure report.
- Isolated cleanup catches each database-owner failure independently and
  continues attempting the remaining owners.

## Historical Residue Reconciliation

- Admitted suffixes: `6a3df99f1f5f`, `6a63a9857752`, and `7af8b3e2d733`.
- All eight dev databases contained the same three service-scoped schemas.
- Every schema matched the exact `.7` acceptance naming contract and contained
  its canonical `schema_migrations` table.
- No canonical acceptance container was running during reconciliation.
- The 24 admitted schemas were dropped explicitly by their owning roles.
- Post-cleanup inventory returned zero `m1_01b7_%` schemas in all eight dev
  databases.

## Verification

- Focused Python regression: `20 passed`.
- Focused Playwright harness regression: `11 passed`.
- Full AE Web regression: `386 passed`.
- AE Slice Gate: `PASS`, `6/6` commands, 569.964 seconds.
- AE Slice Gate coverage: statement `96.40%`, branch `94.64%`.
- Historical residue reconciliation: `PASS`, eight databases at zero.
- Database migration: none.
- Public API change: none.

The exact-head OCI build and protected live rerun remain required before this
corrective Slice can close.
