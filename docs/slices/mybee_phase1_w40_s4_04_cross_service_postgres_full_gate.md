# W40-S4-04 Cross-Service PostgreSQL and Repository Full Gate

## Outcome

PASS / CLOSED. The current canonical EOS, OA, WC, and AE paths were exercised
against their actual PostgreSQL test databases, followed by the complete
Repository Full Gate. No product source, contract, schema, or migration change
was required by this gate.

## Database Identity Admission

The protected run first verified the connected database and role identities:

| Service | Database | Role | Result |
|---|---|---|---|
| NeX-EOS | `nex_eos_test` | `nex_eos_user` | PASS |
| NeX-OA | `nex_oa_test` | `nex_oa_user` | PASS |
| NeX-WC | `nex_wc_test` | `nex_wc_user` | PASS |
| NeX-AE | `nex_ae_test` | `nex_ae_user` | PASS |

Credentials were supplied only through the protected process environment and
are not retained in this evidence.

## Actual PostgreSQL Protected Smoke

The source-current protected matrix ran these exact tests:

```text
tests/test_nex_eos_mybee_posting_replay_pg.py
tests/test_nex_oa_eos_mybee_project_entitlement_lifecycle.py::test_actual_postgres_lifecycle_reconciliation_and_zero_residue
tests/test_ae_wc_p7_s8_postgres_smoke.py::test_s8_actual_postgres_failure_recovery_and_zero_residue
tests/test_nex_wc_p8_s43_human_approval_protected_gate.py::test_s43_actual_oa_wc_postgres_authorization_create_and_decision_gate
```

Result:

```text
34 passed
0 skipped
1 deprecation warning
elapsed = 11.21s
```

The matrix proves:

- EOS atomic posting, exact replay, payload conflict rejection, outbox retry,
  UNKNOWN commit reconciliation, and zero-residue cleanup;
- EOS-to-OA Project entitlement lifecycle reconciliation and revocation;
- AE-to-WC failure, restart, idempotent replay, and cleanup behavior;
- OA-authorized WC approval creation and decision handling.

Remote generation, embedding, and reranking providers were not required for
these persistence and trust boundaries.

## Repository Full Gate

The canonical command completed with exit code `0`:

```text
./scripts/quality/run_quality_gate.sh
```

Python regression and coverage:

```text
tests                = 21886 passed, 167 skipped
warnings             = 1626
elapsed              = 2714.14s
statement coverage   = 96.73% (threshold 96.00%)
branch coverage      = 95.89% (threshold 94.00%)
product statement    = 98.49%
product branch       = 97.06%
harness statement    = 94.19%
harness branch       = 92.96%
```

Contract and repository audits:

```text
schemas              = 255
examples             = 313
negative examples    = 257
OpenAPI documents    = 10
contract validation  = PASS
transition audit     = PASS
dependency audit     = PASS
generation binding   = Qwen3.5-9B on canonical port 9111
```

AE Web acceptance also passed after the production build:

```text
journeys             = 6/6
checks               = 71/71
screenshots          = 16
desktop viewport     = 1440x900
mobile viewport      = 390x844
failed journeys      = 0
```

Machine-readable evidence:

```text
reports/coverage/coverage.json
reports/coverage/coverage-hotspots.json
reports/coverage/junit.xml
reports/uiux/full-web-acceptance-v2/receipt.json
```

## Historical Harness Maintenance Notes

An initial broad run intentionally included two older protected harnesses and
identified maintenance drift outside the canonical matrix:

1. the P8-S53 harness recalculates identity from a mutable external NSL source
   checkout, while its admitted lock describes the frozen NSL v0.2 artifact;
2. the P8-S43 browser harness still targets retired credential-login element
   IDs instead of the current authentication-first React shell controls.

These observations did not indicate a database or product runtime failure.
The source-current OA/WC protected database test and the current AE Web full
acceptance both passed. Updating the two historical harnesses remains a
separate corrective-maintenance backlog item so this gate does not rewrite old
Slice evidence opportunistically.

## Entry Decision

```text
EOS/OA/WC/AE actual PostgreSQL protected smoke = PASS
Repository Full Gate                          = PASS
W40-S4-04 post-implementation gate            = CLOSED
```

