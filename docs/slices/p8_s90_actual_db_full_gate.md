# P8-S90: Actual DB Full Gate

## Status

Completed on 2026-10-24.

## Scope

P8-S90 closes the final P8 PostgreSQL acceptance boundary over the actual
service-owned test databases:

```text
nex_ae_test  / nex_ae_user
nex_wc_test  / nex_wc_user
nex_oa_test  / nex_oa_user
nex_eos_test / nex_eos_user
```

The gate performs a guarded fresh reset, applies every current migration,
runs the PostgreSQL-only P8 protected inventory, and compares the complete
post-test table state with the fresh migration baseline. RustFS, Playwright,
and live generation provider responsibilities remain assigned to P8-S91 and
P8-S92.

No production API, service behavior, database table, or migration changed in
this Slice. Database credentials and raw private payloads are not retained in
the evidence.

## Guarded Reset And Migration

Before reset, every connection proved its exact expected database and role and
reported `pg_is_in_recovery() = false`. Reset was permitted only for the four
explicit `_test` databases and `_user` owners. Each public schema was then
recreated under its service owner and migrated from an empty schema.

```text
service       migrations  head                                  result
nex-ae-api            60  2513_ae_voucher_attachment            applied=60 skipped=0
nex-wc                13  1006_wc_approval_foundation           applied=13 skipped=0
nex-oa                18  1376_oa_trace_projection_index        applied=18 skipped=0
nex-eos               14  2513_eos_voucher_attachment_lineage   applied=14 skipped=0
```

The fresh baseline contained 133 public tables. Only the three canonical AE
prompt-registry seed tables contained business rows:

```text
ae_prompt_templates          = 1
ae_prompt_template_versions  = 1
ae_prompt_bindings           = 1
```

The residue verifier therefore recorded every table's row count and canonical
row-content digest instead of assuming that every migrated table must be
empty.

## Drift Found And Closed

The first protected run correctly failed with `68 passed / 6 failed` and
exposed two pre-existing acceptance drifts:

1. P8-S31 still hard-coded WC migration head
   `1005_wc_assignment_execution`, although the canonical inventory now ends
   at `1006_wc_approval_foundation`.
2. The local `.venv` loaded `nex-skill-language 0.1.0`, while the actual-wheel
   PostgreSQL tests require the admitted P8 v0.2 wheel.

The S31 assertion now compares the complete applied migration set with the
current `load_migrations("nex-wc")` inventory. The admitted wheel was verified
against the canonical lock and installed without changing repository
dependencies:

```text
package version = 0.2.0
wheel sha256    = sha256:862958a5eab982a71bec5ee58b9e530867d6c25f65d8b770efb29ca78ce7f135
source revision = c0a8d4e125ee129c4556d896356237bb3973582d
```

The stale source revision in the P8-S89 evidence was also corrected to the
current lock identity. The four databases were reset and migrated again before
the accepted run; no failed-run state was reused.

## Protected PostgreSQL Evidence

The accepted run selected 38 P8 PostgreSQL modules and enabled every
corresponding DB guard. Comparing the same test identities with the P8-S89
JUnit evidence proves that 40 protected DB cases changed from explicit skip to
actual execution:

```text
P8-S89 selected population  = 34 passed / 40 protected skips
P8-S90 selected population  = 74 passed / 0 skipped
failures / errors           = 0 / 0
duration                    = 55.65 seconds
```

The protected cases cover WC delegation budgets and cycle/authority checks,
human approval, AE approval request/wait/evidence/inbox/idempotency/write
evidence, admitted NSL v0.2 execution, EOS organization/project/account and
Voucher persistence, reconciliation and verification, Golden A fixture
readiness, formal approval, and approval-event/worker-crash recovery.

JUnit evidence is stored locally at:

```text
reports/quality/p8-s90-postgres.junit.xml
```

The report remains under the intentionally ignored `reports/` tree.

## Zero-Residue Proof

After all 74 cases completed, the gate re-read every public table in all four
databases and compared both row count and canonical row-content digest with the
fresh migration baseline:

```text
database identities checked = 4 / 4
table fingerprints checked  = 133
missing tables               = 0
unexpected tables            = 0
row-count differences        = 0
row-content differences      = 0
database residue             = 0
```

The focused post-formatting S31 PostgreSQL re-run also completed with `3
passed`; the same residue comparison remained unchanged.

## Regression And Quality Evidence

```text
ruff changed test                              = PASS
focused S31 actual PostgreSQL                  = 3 passed
P8 filename-scoped regression                  = 1,787 passed / 63 protected skips
P8 contract hygiene                            = PASS
contract inventory                             = 191 schemas / 255 positive
                                                  / 221 negative / 9 OpenAPI
reference / parity / terminology checks        = 1,050 / 25 / 21
canonical P8-S89 coverage                      = 96.72% statement / 96.11% branch
```

Coverage was not remeasured because P8-S89 already closed the unchanged
production source tree. P8-S90 changes one protected test assertion and
documentation only.

## Exit Decision

P8-S90 is closed. AE, WC, OA, and EOS were proven against freshly migrated
actual PostgreSQL test databases, all selected protected cases executed
without skip, the admitted NSL v0.2 wheel was used where required, and the
complete 133-table state returned exactly to baseline. P8-S91 may now run the
authenticated IA Playwright full gate.
