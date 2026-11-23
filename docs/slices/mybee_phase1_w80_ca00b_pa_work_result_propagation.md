# W80-CA00B: PA WorkResult to IA Business Result Propagation Closure

**Status:** CLOSED

**Exact-head acceptance:** `102390b5`

## Scope

- add a shared hash-bound WorkResult business projection contract;
- project admitted PA business output through the existing WC outbox event;
- restore that output into the delegated IA StepResult;
- reuse existing IA plan finalization and workspace publication;
- preserve legacy events and existing persistence structures.

## Verification

- focused regression: initial `112 passed`; exact failing-shape correction
  `41 passed`;
- actual AE/WC PostgreSQL smoke: `28/28` checks, one WorkResult and one resume
  RuntimeJob;
- AE Slice Gate after the exact-head correction: `6,925 passed`, statement
  `96.45%`, branch `94.68%`;
- WC Slice Gate: `748 passed`, statement `97.48%`, branch `94.81%`;
- shared-runtime projection tests: `15 passed`, module coverage `100%/100%`;
- shared-runtime Slice Gate: `2,166 passed`, statement `87.12%`, branch
  `84.24%`;
- AE Web Node regression: `395 passed`;
- AE Web React regression: `29 files / 134 passed`;
- TypeScript, production build, browser-security, import-boundary, and legacy
  retirement audits passed;
- canonical OCI release set: `9/9` images, `9/9` non-root checks, `12`
  background-process checks, no registry push;
- actual isolated eight-database journey: `210` migrations, two non-identical
  requests, six approval decisions, two immutable journals, two allocation
  batches, four allocation lines, four P&L projections, two AgentResults, and
  two acknowledged result deliveries;
- actual DGX generation: `Qwen3.5-9B`, immutable revision
  `hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a`;
- Playwright: `15` main-journey captures and `2` restart-recovery captures;
- restart acceptance: result hash and business references stable, both
  journals/batches/AgentResults retained;
- cleanup: all eight isolated databases dropped with zero residue.

The first exact-head replay proved the PA -> WC -> AE projection transport and
failed closed when IA resume incorrectly required a single EOS operation from a
valid multi-operation allocation result. The corrected contract preserves all
operation lineage and leaves primary identity unset unless a typed summary
declares it. A second exact-head replay exposed that the authentication-first
shell removed the admitted `interaction_id` query during session bootstrap.
The Web route now preserves exactly one UUID recovery target for `/workspace`
and drops malformed or mixed query parameters. The final exact-head OCI/live
replay passed, including authoritative result recovery after restart.
