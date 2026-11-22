# CP-M1-GA-RET-02A.3: Ownership-Aware Coverage Reporting and Quarantine Guard

## Status

- State: `CLOSED`
- Date: `2026-11-16`
- Parent: `CP-M1-GA-RET-02A`
- Entry commit: `306279cf`
- Database migration: none
- Public API change: none
- Remote provider: not required

## Goal

Make AE coverage ownership and Golden A quarantine checks a mandatory part of
the normal AE Slice Gate. A coverage run must fail closed when an owned source
module is absent from the coverage report, a historical source hash changes,
or a quarantined source becomes reachable from the active runtime or canonical
deployment inputs.

## Gate Integration

`ServiceProfile` now supports an exact `coverage_reporters` contract. The AE
profile registers only:

```text
scripts/quality/report_ae_coverage_ownership.py
```

After pytest and the existing coverage, contract, Golden-journey and
demo/product dependency checks finish, the Slice Gate invokes the reporter
with the same coverage JSON. Its output path is deterministic:

```text
reports/coverage/<coverage-stem>.report_ae_coverage_ownership.json
```

The reporter process is part of the Gate command list. Any non-zero result
therefore fails the complete Slice Gate rather than leaving ownership analysis
as an optional follow-up command.

## Ownership Completeness

The semantic-hash-bound ownership manifest still classifies all 176 AE Python
modules into active product, active compatibility, or historical quarantine.
When a coverage report is supplied, every classified source must be present.
The package-only `nex_ae_api/__init__.py` is the sole explicit optional path
because coverage.py does not emit an entry for the empty namespace file.

The generated evidence records:

- missing owned modules in `coverage_unreported_modules`;
- coverage entries outside AE in `foreign_coverage_file_count`;
- aggregate, active-product, compatibility and historical scope metrics; and
- one fail-closed `coverage_inventory_complete` check.

An empty coverage report was verified to fail with 175 missing owned modules,
while the explicit namespace-file exception remains excluded from that list.

## Quarantine Guard

The A1 quarantine guarantees remain mandatory in every integrated report:

1. all historical source hashes match the admitted manifest;
2. the declared historical scope matches the quarantine registry;
3. no historical module is reachable from the recursive active import graph;
4. no historical module appears in canonical deployment inputs; and
5. the manifest semantic content hash remains valid.

Historical tests and files remain visible for regression and provenance. They
are not counted as active-product margin and cannot silently re-enter the
installed runtime.

## Checkpoint Reconciliation

The first repository Checkpoint found one stale W40 source-text assertion. It
still required `agent_runtime_process.py` to call the retired direct
`build_installed_mybee_voucher_candidate_consumer()` binding even though A0
had promoted installed execution through the product executor profile and the
generic runtime-composition factory.

The test now proves the current product contract instead:

- the canonical worker selects `build_product_runtime_executor_profile()`;
- execution is assembled by `build_installed_runtime_composition()`;
- the retired direct consumer builder is absent from the process; and
- no separate `nex-mybee` service is introduced.

No product source was changed. The corrected focused test passed and the
repository Checkpoint was rerun from the beginning.

## Verification

```text
focused quality/reporter regression      31 passed
AE Slice Gate                            6,225 passed / 46 protected skips
AE Slice Gate files                      434
AE Slice Gate commands                   6 / 6, PASS
AE Slice Gate duration                   482.096 seconds
aggregate statement / branch             96.3908% / 94.5663%
active product statement / branch        97.0695% / 94.8851%
compatibility statement / branch         61.9238% / 62.9630%
historical statement / branch            86.8421% / 81.7647%
owned / reported / optional modules       176 / 175 / 1
foreign coverage entries                 0
historical active/deployment conflicts   0 / 0
ownership checks                         7 / 7, PASS
stale installed-runtime regression       8 passed
Repository Checkpoint                    22,199 passed / 178 protected skips
Repository Checkpoint commands           5 / 5, PASS
Repository statement / branch            98.4001% / 96.9544%
Repository Checkpoint duration           1,655.897 seconds
ruff                                     PASS
```

Generated evidence remains under ignored report paths:

```text
reports/quality/mybee-w70-ga-ret-02a3-ae.coverage.json
reports/coverage/mybee-w70-ga-ret-02a3-ae.coverage.report_ae_coverage_ownership.json
reports/quality/slice-latest.json
reports/quality/mybee-w70-ga-ret-02a3-checkpoint.coverage.json
reports/quality/checkpoint-latest.json
```

## Exit

AE ownership reporting is now enforced by the ordinary Slice Gate, and the
quarantine boundary fails closed for coverage omission, hash drift, active
import reachability, or deployment re-entry. The next boundary is
`CP-M1-GA-RET-02A.4: Project Delegation Active Branch Hardening`.
