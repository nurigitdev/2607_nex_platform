# Slice 1394: Platform Generation Golden Scenarios

## Outcome

- Added a typed, exact ten-scenario matrix for `GEN-E2E-001` through
  `GEN-E2E-010`.
- Added one deterministic aggregate runner that executes existing AE, CX, MO,
  and AG production functions and in-memory service flows.
- Exercised general-answer routing, grounded trace continuity, MD/DOCX report
  rendering, no-answer and low-confidence guards, compatibility rejection,
  timeout recovery, bounded citation repair, render retry, owner-only artifact
  access, and redacted AG audit packaging.
- Returned only boolean signals, component identities, and SHA-256 evidence
  digests. Raw prompts, source/generated text, files, storage references,
  provider endpoints, credentials, and database URLs are excluded.
- Kept PostgreSQL, remote providers, and browsers outside this deterministic
  Slice. Their protected evidence remains required by S140 and cannot be
  replaced by this runner.

## Verification

```bash
scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_nex_runtime_generation_golden.py \
  --coverage-target services/_shared/nex_runtime/generation_golden.py \
  --coverage-target scripts/smoke/run_platform_generation_golden_scenarios.py \
  --smoke scripts/smoke/run_platform_generation_golden_scenarios.py
```

The runner must report `scenarios=10/10`, `protected=0`, `privacy=0`, and
`next=1395`.

Observed result:

- `988 passed`, `11 skipped`
- statement coverage: `98.49%` (threshold `95.00%`)
- branch coverage: `97.84%` (threshold `94.00%`)
- `generation_golden.py`: statement `100.00%`, branch `100.00%`
- aggregate runner: statement `100.00%`, branch `100.00%`
- contract validation: `166` schemas, `228` positive examples, `196`
  negative examples, `7` OpenAPI documents
- golden scenarios: `10/10`, protected executions: `0`, privacy violations:
  `0`, next Slice: `1395`

The eleven skipped `nex-oa` protected smoke tests are expected in this
deterministic Slice and are not accepted as S140 protected release evidence.
