# Slice 1361: S136 Permission Hybrid Retrieval Closure

## Outcome

- Closed S136 against the permission-filtered hybrid retrieval completion
  signal and activated the S137 grounded-generation handoff.
- Aligned `cx_retrieval_context_package.v1` with the owner-scoped calibrated
  runtime and added explicit READY and NO_ANSWER examples.
- Bound retrieval status to evidence cardinality, multi-signal calibration,
  weighted-RRF policy, safe provider identity, and hash-only persistence.
- Added the protected operator runbook for execution, model replacement,
  recalibration, failure triage, cleanup, rollback, and privacy handling.
- Added deterministic closure evidence over six PASS components and three
  protected opt-in components.

## Decision

S136 is complete. S137 inherits only a contract-valid owner-scoped retrieval
package with a READY, LOW_CONFIDENCE, or NO_ANSWER decision and complete
permission, candidate, ranking, provider, calibration, and evidence lineage.
Generation, citation validation and repair, AE response lineage, rendering,
preview, download, and artifact lifecycle remain owned by S137.

The Full Gate does not repeat protected PostgreSQL/provider mutation. Slice
1360 records the actual `nex_cx_test` plus live embedding/reranker result;
ordinary closure regression verifies that all protected runners skip safely
unless explicitly enabled.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_s136_permission_hybrid_retrieval_closure.py \
  tests/test_nex_cx_hybrid_retrieval_package.py

./.venv/bin/python scripts/quality/validate_contracts.py

./.venv/bin/python \
  scripts/smoke/run_s136_permission_hybrid_retrieval_closure.py --summary

scripts/quality/run_quality_gate.sh
```

Protected live evidence is rerun separately with
`NEX_S136_PERMISSION_HYBRID_LIVE_POSTGRES_SMOKE=1` and operator-injected test
database/provider configuration. No credential value is committed or emitted.

Final verification results:

- focused closure and retrieval-package regression: `61 passed`
- contract validation: schemas `161`, examples `220`, negative examples
  `188`, OpenAPI documents `7`
- deterministic closure: `13/13` checks, six PASS components and three
  protected opt-in SKIP components, `READY_FOR_S137`
- protected `nex_cx_test` plus live embedding/reranker execution: `17/17`
  checks with READY, LOW_CONFIDENCE, and NO_ANSWER, followed by zero fixture
  residue
- Full Gate: `11,478 passed`, `31` policy-skipped protected tests
- source coverage: statements `98.06%`, branches `96.99%`

## S137 Handoff

S137 must retain exact calibration binding and permission-first retrieval. It
must not bypass LOW_CONFIDENCE/NO_ANSWER decisions, read another owner's
package, persist private retrieval text in operations evidence, or call a
provider outside the CX-to-MO capability boundary.
