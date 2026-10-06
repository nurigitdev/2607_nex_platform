# Platform MVP Release-Candidate Acceptance Runbook

## Purpose

This runbook closes S140 by combining a fresh protected eight-gate matrix with
the repository Full Gate. A passing result declares an MVP release candidate,
not production deployment approval.

## Preconditions

- Run from the repository root in the office network where the three remote
  provider capabilities are reachable.
- Export the five service-owned test database URLs through local secret
  injection. Every target must be a `nex_*_test` database.
- Export the live embedding, reranking, and generation provider configuration
  through local secret injection.
- Select `SIGNED_ONLY` service trust, API-only AG operations, OA-backed AE
  sessions, live MO provider mode, and desktop plus mobile browser viewports.
- Confirm no production database, production object store, or external
  notification endpoint is selected.

## Protected Matrix Command

Enable the protected profile and write metadata-only evidence outside source
control:

```bash
export NEX_S140_RELEASE_CANDIDATE_PROTECTED_MATRIX=1
./.venv/bin/python \
  scripts/smoke/run_platform_release_candidate_protected_matrix.py \
  --output /tmp/nex-s140-protected-matrix.json \
  --summary
```

Expected summary:

```text
platform_release_candidate_protected_matrix=pass gates=8/8 protected=5/5 pending_full=1 privacy=0 next=1401
```

Stop if any count differs. Do not continue by editing the evidence file or
marking the pending Full Gate as passed.

## Full Gate And Closure Command

The Full Gate creates `reports/coverage/junit.xml` and
`reports/coverage/coverage.json`. Its final registered runner replaces exactly
one `full_regression` placeholder and reuses the canonical nine-gate evaluator.

```bash
export NEX_S140_RELEASE_CANDIDATE_CLOSURE=1
export NEX_S140_PROTECTED_EVIDENCE_PATH=/tmp/nex-s140-protected-matrix.json
export NEX_S140_CLOSURE_EVIDENCE_PATH=/tmp/nex-s140-release-candidate.json
scripts/quality/run_quality_gate.sh
```

The final summary must report `gates=9/9`, `protected=5/5`, `privacy=0`, and
`decision=RELEASE_CANDIDATE`. The statement threshold remains `95%` and the
branch threshold remains `85%`.

## Expected Evidence

- ten named golden scenarios pass;
- all five test databases restart, restore, and clean up;
- embedding, reranking, and generation capabilities pass with the selected
  runtime model identities and matching calibration;
- desktop and mobile Korean browser journeys pass;
- AG reconstructs all eight trace families and exports a redacted audit;
- contracts, privacy, recovery, zero-residue, and deployment-deferral checks
  pass;
- Full Gate reports at least one passing test, no failed test, and coverage at
  or above both repository thresholds;
- the final evaluator reports all nine gates passed and five protected gates
  actually executed.

## Accepted Slice 1401 Evidence

The accepted S140 execution reported `8/8` protected non-regression gates,
`5/5` actual protected gates, and zero privacy violations before Full Gate.
Full Gate then reported `12,010 passed`, `31 skipped`, statement coverage
`98.11%`, branch coverage `97.01%`, and contract validation of `166` schemas,
`228` examples, `196` negative examples, and `7` OpenAPI documents. The final
closure reported `9/9`, `protected=5/5`, `privacy=0`, and
`decision=RELEASE_CANDIDATE` while retaining
`production_deployment_approved=false`.

## Failure Triage

1. An admission failure means the protected profile, exact test database
   identities, provider capabilities, trust mode, or viewports are incomplete.
2. A provider failure must be diagnosed through MO capability aliases and the
   model-bound calibration identity. Do not hard-code a model name or lower a
   confidence threshold to obtain a pass.
3. A browser or trace failure must preserve same-origin AE access and
   service-API-only AG projection. Do not read another service database.
4. A residue failure requires cleanup and a fresh protected run before Full
   Gate.
5. A Full Gate test, contract, or coverage failure blocks the release
   candidate. Fix the regression and rerun both commands so evidence remains
   fresh and internally consistent.

## Cleanup Verification

- Confirm the protected runner reports zero database, file, and process
  residue.
- Confirm all temporary service processes and browser processes have stopped.
- Treat `/tmp/nex-s140-protected-matrix.json` and
  `/tmp/nex-s140-release-candidate.json` as short-lived operator evidence.
  Remove them after the accepted result has been recorded.
- Never commit runtime evidence, coverage reports, credentials, endpoints,
  private payloads, or storage references.

## Rollback And Fail-Closed

- If either command fails, S140 remains blocked and the previous service-level
  MVP closures remain the rollback baseline.
- Do not reuse an older protected matrix to mask a current failure.
- Do not retry automatically across a profile or model-identity change.
- `production_deployment_approved` must remain `false` in every S140 result.

## Production Deferrals

External signing-key custody, managed TLS, production secret rotation,
enterprise identity-provider registration, production object storage,
production PostgreSQL backup and high availability, external incident
endpoints, production GPU scheduling, and production monitoring/change
approval remain explicit post-MVP work.
