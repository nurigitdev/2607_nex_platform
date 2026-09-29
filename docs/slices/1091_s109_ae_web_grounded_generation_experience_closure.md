# Slice 1091: S109 AE Web Grounded Generation Experience Closure

## Goal

Close S109 with machine-checkable evidence that the authenticated AE Web
surface owns a complete, privacy-safe, asynchronous grounded-generation user
experience backed by durable AE/CX state and live providers.

## Closure

- AE Web communicates only with the same-origin AE API facade. Browser code
  receives no CX/MO direct endpoint, service token, provider credential,
  database URL, or private storage path.
- AE API owns orchestration and exact-owner verification, CX owns retrieval and
  grounded generation, and MO owns provider execution.
- The browser lifecycle covers async admission, bounded progress polling,
  durable refresh, terminal response retrieval, and citation-quality lookup.
- Cancel, recovery inspection, and retry are explicit, race-safe actions.
- Generated text is presented only after owner verification and citation
  quality gating; artifact handoff remains blocked until verified completion.
- Runtime diagnostics and accessibility evidence expose lifecycle state without
  prompt, response, source, database, provider, or credential material.
- Actual `nex_ae_test` and `nex_cx_test` evidence proves the browser-to-worker
  path with live embedding, reranking, and generation providers and zero
  owner-scoped probe residue.
- No database table was added for S109. Existing AE workspace/chat/generated
  response and CX content/retrieval/generation/job persistence was reused.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_s109_ae_web_grounded_generation_experience_closure.py
scripts/quality/run_slice_gate.sh --service nex-ae-web \
  --test tests/test_s109_ae_web_grounded_generation_experience_closure.py \
  --coverage-target scripts/smoke/run_s109_ae_web_grounded_generation_experience_closure.py \
  --smoke scripts/smoke/run_s109_ae_web_grounded_generation_experience_closure.py
scripts/quality/run_quality_gate.sh
```

## Observed Evidence

- Protected Slice 1090 execution: checks `16/16`, providers `3/3`, browser
  display `VERIFIED_RESPONSE`, and both actual test databases verified.
- Protected S109 closure: components `10/10`, gaps `8/8`, live checks
  `16/16`; next requirement `S110`. Owner-scoped probe residue was zero in
  both actual test databases after cleanup.
- Full Gate: `8,750 passed`, `5 skipped`; statement coverage `98.81%`, branch
  coverage `96.85%`; contracts `108` schemas, `166` examples, `129` negative
  examples, and `7` OpenAPI documents; AE Web Node regression `293 passed`.
- The default Full Gate kept the protected live smoke opt-in and reported it as
  skipped while independently passing the S109 closure at components `10/10`
  and gaps `8/8`.
