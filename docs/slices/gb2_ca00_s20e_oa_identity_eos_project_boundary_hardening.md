# GB2-CA00-S20E: OA Identity and EOS Project Boundary Hardening

## Scope

- Harden `nex_oa.subjects` integrity, metadata, serialization, and unavailable-store branches.
- Harden `nex_eos.project_operations` malformed input, authorization, replay, and partial batch-result branches.
- Preserve existing APIs and persistence schemas; this Slice adds regression evidence only.
- Keep the Slice independent of remote generation, embedding, and reranking providers.

## Changes

- Added focused OA identity tests for integrity-conflict replay, repository failures, metadata normalization, JSON fallback, and timestamp wire conversion.
- Added focused EOS project-operation tests for invalid operation names, malformed batch requests, subject normalization, authorization denials, hash mismatch, and mixed member outcomes.
- Verified the existing PostgreSQL migrations and repository paths against `nex_oa_test` and `nex_eos_test`.

## Verification

- Focused regression: `57 passed`.
- OA protected PostgreSQL identity lifecycle smoke: `19 passed`.
- EOS protected PostgreSQL project-operation smoke: `1 passed`.
- OA Slice Gate: `1,147 passed, 11 skipped`; service statement `97.30%`, branch `96.18%`; `subjects.py` statement `98.13%`, branch `97.30%`.
- EOS Slice Gate: `764 passed, 22 skipped`; service statement `95.89%`, branch `94.49%`; `project_operations.py` statement `97.51%`, branch `94.34%`.
- Contract validation, golden-journey transition audit, and demo/product dependency audit passed in both gates.

Protected tests skipped by the ordinary Slice Gates were not treated as database evidence; the OA and EOS PostgreSQL smoke suites were enabled and executed separately with their actual test database URLs.

## Outcome

OA identity and EOS governed-project edge behavior now has explicit regression coverage with actual PostgreSQL evidence. No remote provider was required, so work can continue in the current environment.
