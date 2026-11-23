# W80-CA00B: PA WorkResult to IA Business Result Propagation Closure

## Scope

- add a shared hash-bound WorkResult business projection contract;
- project admitted PA business output through the existing WC outbox event;
- restore that output into the delegated IA StepResult;
- reuse existing IA plan finalization and workspace publication;
- preserve legacy events and existing persistence structures.

## Verification

- focused regression: `112 passed`;
- actual AE/WC PostgreSQL smoke: `28/28` checks, one WorkResult and one resume
  RuntimeJob;
- AE Slice Gate: `6,923 passed`, statement `96.44%`, branch `94.66%`;
- WC Slice Gate: `748 passed`, statement `97.48%`, branch `94.81%`;
- shared-runtime projection tests: `15 passed`, module coverage `100%/100%`;
- shared-runtime Slice Gate: `2,166 passed`, statement `87.12%`, branch
  `84.24%`.

Exact-head installed live journey replay remains pending after the implementation
commit and OCI rebuild.
