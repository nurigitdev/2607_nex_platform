# Slice 1393: Platform Release-Candidate Gate Matrix

## Outcome

- Added a shared typed S140 gate matrix with nine blocking gate identities.
- Split deterministic evidence from five protected gates without permitting a
  protected gate to pass on deterministic evidence.
- Added exact inventory, duplicate-ID, freshness, digest, privacy, skip, and
  production-claim rejection.
- Added gate-specific metrics for ten golden scenarios, five databases, three
  providers, two viewports, eight trace stages, contracts, regression,
  zero-residue, and deployment deferrals.
- Kept the sample runner deterministic; no database, provider, or browser was
  contacted.

## Verification

```bash
scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_nex_runtime_release_candidate.py \
  --coverage-target services/_shared/nex_runtime/release_candidate.py \
  --coverage-target scripts/smoke/run_platform_release_candidate_gate_matrix.py \
  --smoke scripts/smoke/run_platform_release_candidate_gate_matrix.py
```

The runner must report nine passing gates, five actual protected gate
identities, and `next=1394`.

Observed result:

- `996 passed`, `11 skipped`
- statement coverage: `98.45%` (threshold `95.00%`)
- branch coverage: `97.75%` (threshold `94.00%`)
- `release_candidate.py`: statement `98.20%`, branch `95.45%`
- gate-matrix runner: statement `100.00%`, branch `100.00%`
- contract validation: `166` schemas, `228` positive examples, `196`
  negative examples, `7` OpenAPI documents
- deterministic matrix result: `9/9` gates, `5/5` protected gate
  identities, `next=1394`

The protected smoke tests skipped by the `nex-oa` Slice Gate remain expected
at this stage. Their skipped state is not S140 release evidence; later Slices
must replace it with fresh protected evidence before the release-candidate
decision can pass.
