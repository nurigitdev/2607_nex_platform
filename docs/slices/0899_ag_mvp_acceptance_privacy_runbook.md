# Slice 0899: AG MVP acceptance privacy and failure runbook

## Goal

Turn every NeX-AG MVP acceptance blocker and two-stage handoff integrity failure
into deterministic, privacy-safe operator evidence and remediation guidance.

## Implementation

- Replays missing, skipped, stale, future-dated, regression, statement/branch
  coverage, wrong-database, cleanup, runbook, and handoff gate failures through
  the production fail-closed evaluator.
- Verifies the successful eight-gate acceptance path and both stages of the CX
  handoff, then proves candidate and attestation tampering are rejected.
- Defines operator actions for evidence freshness, regression/coverage,
  contracts/inventory, PostgreSQL connectivity/migration, wrong database,
  cleanup residue, runbook inventory, candidate integrity, and attestation
  integrity failures.
- Requires every Slice 0891-0898 document, the default quality-gate hook, and
  Slice 0898's actual `nex_ag_test` acceptance, migration, coverage, BOUND
  attestation, and zero-residue evidence.
- Excludes raw documents, prompts, generations, event details, database URLs,
  authorization values, and credentials from all evidence surfaces.
- Introduces no table or migration.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_ag_mvp_acceptance_privacy_runbook_evidence.py \
  --cov=run_ag_mvp_acceptance_privacy_runbook_evidence \
  --cov-branch --cov-report=term-missing

./.venv/bin/python \
  scripts/smoke/run_ag_mvp_acceptance_privacy_runbook_evidence.py \
  --summary
```

Observed verification:

```text
focused runbook tests: 9 passed
runbook evidence statement/branch coverage: 100%
ag_mvp_acceptance_privacy_runbook=pass surfaces=8 privacy=True postgres=True runbook=True
aggregate regression: 6265 passed, 1 known warning
statement=75504/76385=98.84663219218433%
branch=17648/18298=96.44769920209859%
```
