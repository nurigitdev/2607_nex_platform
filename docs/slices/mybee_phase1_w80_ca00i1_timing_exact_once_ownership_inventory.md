# W80-CA00I.1 Timing and Exact-Once Ownership Inventory

## Outcome

- Added command-level duration and exit-code evidence to the existing tiered
  Slice and Checkpoint Gate executor.
- Added `run_parallel_quality_gate.py inventory` for deterministic repository
  test discovery, owner-profile candidate resolution, serial classification,
  and hash-bound inventory evidence.
- Reused `nex_runtime.semantic_hashes` for the canonical inventory digest.
- Preserved the existing serial Checkpoint and Repository Full Gate execution;
  this Slice changes observation and admission only.

## Ownership Rules

| Candidate owners | Canonical assignment |
| --- | --- |
| Exactly one | Owner-service lane |
| More than one | `serial-integration` |
| None | `serial-repository` |

The resulting assignment is exact-once. Source ambiguity remains visible in
the receipt and is not silently treated as owner-service work.

## Actual Repository Evidence

| Tier | Test files | Source unowned | Source multi-owned | Resolved missing | Resolved duplicate |
| --- | ---: | ---: | ---: | ---: | ---: |
| Checkpoint | 1761 | 211 | 77 | 0 | 0 |
| Full | 1877 | 322 | 77 | 0 | 0 |

Checkpoint inventory digest:

```text
sha256:95ae08da08e827bef45d1fa22507cf063fbe8c3a61476ccd96709d3603b651b2
```

Full inventory digest:

```text
sha256:ffa9b08cb17eca74ddb5269247f76ba6b8717bf3e7f2c3a491acd7124b0fda2b
```

The inventory receipts are generated under
`reports/quality/parallel/<run-id>/` and remain run evidence rather than source
configuration.

## Verification

```text
33 passed
run_parallel_quality_gate.py: 100% statement/branch coverage
combined focused modules: 99% coverage
checkpoint exact-once inventory: PASS
full exact-once inventory: PASS
git diff --check: PASS
```

No database, API, migration, runtime deployment, browser, or provider boundary
changed. W80-CA00I.2 may now isolate every lane's coverage, JUnit, logs, and
evidence paths before any concurrent execution is admitted.
