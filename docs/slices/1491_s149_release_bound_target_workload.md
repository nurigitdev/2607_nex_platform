# Slice 1491: S149 Release-bound Target Workload

Status: Complete. Protected execution requires explicit opt-in and produces an
ignored metadata-only report.

## Outcome

- Added a protected live soak profile bound to the exact S1490 release
  candidate and immutable six-image release-set digest.
- Preserved the target `1,800` second measurement window, concurrency `4`,
  target `4 RPS`, and exactly `7,200` scheduled operations.
- Replaced the deterministic equal-weight mix only for protected execution.
  The live plan explicitly caps embedding at `450`, reranking at `450`, and
  generation at `30` calls while keeping every required operation present and
  interleaved across the run.
- Added actual pre/post authenticated-ingestion and
  grounded-generation/artifact journey sentinels.
- Added actual five-test-database probes, CX rehearsal-owned persistence,
  remote embedding/reranking/generation calls, pool saturation observation,
  metadata-only aggregation, and exact residue cleanup.
- Kept model names and revisions entirely environment/catalog driven. No S149
  workload constant depends on Qwen or any other specific model.
- Added per-operation outcome admission so the aggregate error-rate budget
  cannot conceal failure of all low-frequency generation or retrieval probes.
  Hybrid retrieval and grounded generation must each achieve exact full
  success counts.

## Decision

The 7,200-request load interval is a bounded PostgreSQL/provider boundary
workload, surrounded by complete actual business-journey sentinels. It must not
be described as 7,200 browser or upload-to-artifact E2E journeys. This preserves
an operationally safe GPU budget while proving that the real journeys remain
healthy before and after sustained load.

Slice 1492 owns fault, security/privacy, and rollback execution under this
active workload. Slice 1493 owns aggregate admission and backlog
classification. Slice 1494 owns runbook publication and the Full Gate.

## Protected Execution

Execution requires all five `NEX_*_TEST_DATABASE_URL` bindings, the three live
remote-provider bindings, a current passing S1490 report, and explicit opt-in:

```bash
NEX_S149_RELEASE_BOUND_TARGET_WORKLOAD=1 \
  ./.venv/bin/python \
  scripts/smoke/run_s149_release_bound_target_workload.py \
  --execute --summary
```

The report is written to
`reports/deployment/s149-release-bound-workload.json`. It contains release and
workload digests, aggregate counts, latency/SLO metrics, sentinel evidence
digests, provider-call counts, and residue counts. It excludes credentials,
endpoint URLs, database URLs, private payloads, and per-request records.

## Verification

- Unit tests cover exact workload admission, weighted interleaving, immutable
  operation/provider budgets, protected opt-in, predecessor binding, every
  admission failure, runtime DB/provider dispatch, cleanup, redaction, and CLI
  behavior.
- The protected runner fails closed on a stale or failed S1490 predecessor,
  failed sentinel, workload/SLO failure, operation-count drift, provider budget
  drift, shortened measurement window, isolation or duplicate side effects,
  or cleanup residue.
- Production resources are not contacted, production-sized capacity is not
  claimed, and production deployment remains unapproved.
