# W80-CA00B: PA WorkResult to IA Business Result Propagation Closure

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
  `84.24%`.

The first exact-head replay proved the PA -> WC -> AE projection transport and
failed closed when IA resume incorrectly required a single EOS operation from a
valid multi-operation allocation result. The corrected contract preserves all
operation lineage and leaves primary identity unset unless a typed summary
declares it. Corrected exact-head OCI/live replay remains pending.
