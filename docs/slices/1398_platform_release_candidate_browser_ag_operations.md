# Slice 1398: Platform Release-Candidate Browser And AG Operations Evidence

## Outcome

- Reused the protected S139 Korean browser acceptance and S138 AG trace
  PostgreSQL smoke instead of adding a second browser or trace implementation.
- Converted the actual desktop/mobile Chromium journey into the typed
  `korean_browser_journey` release-candidate gate.
- Converted the actual five-database, service-API-only trace journey into the
  typed `ag_trace_operations` release-candidate gate.
- Required thirteen service processes, OA-backed login, owner-scoped upload,
  grounded artifact delivery, nine browser stages, both viewports, eight trace
  families, restart-safe AG audit, and zero database/file residue.
- Kept the browser source on its deterministic mock provider boundary. Slice
  1397 independently owns the live provider gate, so UI acceptance does not
  become flaky or repeat expensive model execution.
- Projected only counts, booleans, timestamps, and evidence digests. Browser
  credentials, cookies, database URLs, prompts, source text, generated text,
  artifact content, and audit-private payloads remain excluded.

## Protected Verification

The protected runner was executed with
`NEX_S140_RELEASE_CANDIDATE_BROWSER_AG_OPERATIONS=1` and all five test database
URLs supplied outside source control.

Observed result:

- actual desktop/mobile Chromium: `2/2`
- browser journey stages: `9`
- service processes: `13`
- actual AG trace families: `8`
- restart-safe AG audit exports: `1`
- combined database/file residue: `0`
- next Slice: `1399`

The normal Slice Gate leaves the protected enable flag unset and validates a
deterministic `SKIPPED` result. That skip is not the protected evidence above.

## Quality Verification

```bash
scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_nex_runtime_release_candidate_operations.py \
  --coverage-target services/_shared/nex_runtime/release_candidate_operations.py \
  --coverage-target scripts/smoke/run_platform_release_candidate_browser_ag_operations.py \
  --smoke scripts/smoke/run_platform_release_candidate_browser_ag_operations.py
```

Slice 1399 can now close failure/recovery, privacy, zero-residue, and explicit
deployment-deferral evidence without rerunning the browser or AG journey.

Observed Slice Gate:

- `987 passed`, `11 skipped`
- statement coverage: `98.46%`
- branch coverage: `97.81%`
- both new files: statement `100.00%`, branch `100.00%`
- contract validation: `166` schemas, `228` positive examples, `196`
  negative examples, `7` OpenAPI documents
