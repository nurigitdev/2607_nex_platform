# Slice 1493: S149 Evidence Admission and Backlog Classification

Status: Complete. Execution is metadata-only, explicit opt-in, and consumes the
passing protected reports from Slices 1490-1492.

## Outcome

- Added one fail-closed admission runner for the S1490 Single-host live,
  S1491 release-bound target workload, and S1492 under-load recovery reports.
- Required exact schema and Slice identity, one release-candidate ID, one
  immutable six-image release-set digest, complete predecessor evidence
  digests, and one workload digest.
- Required every nested check, the exact 7,200-request target workload, the
  exact 1,440-request under-load workload, eight recovered faults, disabled
  generation reasoning, and zero database/storage/provider rehearsal residue.
- Classified all five distributed capabilities as
  `NOT_APPLICABLE_SINGLE_HOST` with the future environment needed to prove
  each capability. They are backlog, not mocked success.
- Evaluated S150 as `CONDITIONALLY_READY`, with the Slice 1494 Full Gate and a
  time-bounded external-notification P1 waiver still open.

## Decision

A passing Slice 1493 report means the release candidate is ready for S149
closure. It does not authorize production deployment. `production_go_eligible`
remains false, and the external-notification waiver is
`REQUIRED_NOT_GRANTED` until an authorized release decision records it.

## Execution

```bash
NEX_S149_EVIDENCE_ADMISSION=1 \
  ./.venv/bin/python \
  scripts/smoke/run_s149_evidence_admission.py \
  --execute --summary
```

The ignored report is written to
`reports/deployment/s149-evidence-admission.json`. It contains only digests,
counts, classifications, and decisions; nested raw evidence, credentials,
endpoints, and private payloads are excluded.

## Verification

- Unit tests cover opt-in/profile guards, every admission check, report/schema
  identity, incomplete evidence, malformed JSON, backlog drift, summary, and
  CLI behavior.
- Slice 1494 must consume this exact report, publish the operational runbook,
  pass the Full Gate, and close S149 before S150 can start.
