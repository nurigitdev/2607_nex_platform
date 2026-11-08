# P8-S113: Repository Full Gate, Zero Residue, and Final As-Built v1.2

## Scope

P8-S113 closes P8-CA05/P8.11. It preserves the P8 v1.0 and v1.1 Final
As-Built records and adds v1.2 as the current NVTProject and batch-membership
demonstration handoff.

## Contract Hygiene Reconciliation

The first Full Gate exposed two missing negative fixtures for CA05 contracts.
No runtime defect or accepted-invalid payload was found. S113 added fixtures
that reject:

- an unknown `overall_status` in the batch result projection;
- `model_authority=true` in the batch Skill binding.

Canonical contract validation now passes at `207` schemas, `271` positive
examples, `231` negative examples, and `9` OpenAPI documents. The S101 AE
contract audit remains strict and returned to its historical drift count of
`33`.

## Repository Full Gate

```text
17,650 collected
17,532 passed
118 explicit protected skips
0 failed / 0 errored
statement coverage 96.63% (floor 96.00%)
branch coverage    96.01% (floor 94.00%)
AE Web             386 passed / 0 failed
contracts          207 / 271 / 231 / 9
```

Evidence digests:

```text
coverage.json = sha256:5642ceaf288c26f9c11784beaaebbec3d7f35de0e6420a87f17a90f5dcde7ea5
junit.xml      = sha256:2d1f7af38e872e2951469543daecb56bece62d26716d395101ef7dfb287e6321
```

## Protected Revalidation

The P8-S112 runner was executed after the Full Gate with actual OA, AE, WC,
and EOS PostgreSQL databases, live `Qwen3.5-4B` generation, and authenticated
Chromium Playwright.

```text
checks                = 10 / 10 PASS
NVT CRUD              = PASS
OA batch resolution   = PASS
WC approval           = PASS
EOS exact replay      = PASS
requested/admitted    = 3 / 1
applied/rejected      = 1 / 2
backend residue       = 0
browser cleanup       = PASS
```

The local redacted report digest is
`sha256:46c333edffa254dfe101f17f89a60d0f28ca1dc1795fac4174553f85841fe7cf`.

## Final Baseline

The authoritative additive handoff is:

```text
docs/transition/P8/P8_Final_AsBuilt_Baseline_and_P9_Handoff_v1.2.md
```

P8.11 adds no table or migration. The executable baseline is P8-S112 commit
`afab33eab8f4e4119b9693aa04fb4bf1e01840dd`; the S113 closure commit is
resolved from Git history.

## Exit

```text
P8-CA05 CLOSED
P8.11 CLOSED
DEMO RELEASE CANDIDATE REFRESHED
P9 ENTRY AUTHORIZED
```
