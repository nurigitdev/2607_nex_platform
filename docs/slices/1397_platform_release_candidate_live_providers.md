# Slice 1397: Platform Release-Candidate Live Provider Evidence

## Outcome

- Added one protected S140 runner that reuses the existing remote-provider,
  S136 hybrid retrieval/calibration, and S137 grounded generation/artifact
  journeys instead of introducing a parallel provider path.
- Bound live embedding, reranking, and generation to the typed
  `live_provider_matrix` release-candidate gate.
- Required actual `nex_cx_test` retrieval persistence, all hybrid retrieval
  checks, at least twenty multi-signal calibration samples, actual grounded
  PostgreSQL execution, three live capabilities, and zero cleanup residue.
- Removed the S136 smoke's fixed embedding/reranker model-name admission.
  The selected environment revisions are now observed and bound to the
  calibration profile; capability and contract identity control acceptance.
- Projected model bindings only as a digest plus calibration profile hash and
  selected threshold. Endpoints, credentials, prompts, source text, vectors,
  generated text, and private storage references remain excluded.

## Protected Verification

The first execution correctly failed closed because the generation base URL
included `/v1`, causing the client to construct a duplicate API prefix. The
independent provider smoke identified an upstream `404` only for generation;
embedding and reranking remained healthy. The operator input was corrected to
the server root, after which all three capabilities passed.

The complete protected runner was then executed with
`NEX_S140_RELEASE_CANDIDATE_LIVE_PROVIDERS=1`, actual test database URLs, and
operator-injected provider endpoints and credentials outside source control.

Observed result:

- live provider capabilities: `3/3`
- failed provider capabilities: `0`
- multi-signal calibration samples: `20`
- actual CX and grounded AE/CX PostgreSQL journeys: `PASS`
- grounded artifact residue: `0`
- next Slice: `1398`

The ordinary Slice Gate leaves the protected enable flag unset and therefore
verifies a deterministic `SKIPPED` result. That skip is not the live evidence
recorded above.

## Quality Verification

```bash
scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_nex_runtime_release_candidate_providers.py \
  --test tests/test_s136_permission_hybrid_live_postgres_smoke.py \
  --coverage-target services/_shared/nex_runtime/release_candidate_providers.py \
  --coverage-target scripts/smoke/run_platform_release_candidate_live_providers.py \
  --smoke scripts/smoke/run_platform_release_candidate_live_providers.py
```

Slice 1398 can now bind the Korean browser journey to AG trace, audit, and
operations evidence without repeating model calibration.

Observed Slice Gate:

- `993 passed`, `11 skipped`
- statement coverage: `98.46%`
- branch coverage: `97.81%`
- both new files: statement `100.00%`, branch `100.00%`
- contract validation: `166` schemas, `228` positive examples, `196`
  negative examples, `7` OpenAPI documents
