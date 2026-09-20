# Slice 0893: AG MVP evidence inventory

## Goal

Define the canonical, machine-checkable requirement closure inventory used by
S90 instead of relying on an informal list of completed AG work.

## Inventory Boundary

The inventory contains 33 closure runners and their matching Slice documents:

| Capability group | Requirements | Count |
| --- | --- | ---: |
| Shared generation quality | S34-S38 | 5 |
| AG operations foundation | S53 | 1 |
| AG operator governance | S63-S81 | 19 |
| AG MVP hardening | S82-S89 | 8 |

AE-only S39-S52 and S54-S62 closures are intentionally excluded. Their code is
still exercised by aggregate regression, but they are not represented as AG
requirement ownership.

## Guardrails

- Every included requirement must resolve to exactly one closure runner and
  exactly one closure document.
- Runner identity must contain its S-numbered schema version and `closure.v1`.
- Duplicate, ambiguous, missing, or mismatched evidence is blocking.
- The inventory exposes repository-relative paths and identity status only. It
  does not expose environment values, database URLs, credentials, or raw smoke
  payloads.

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_ag_mvp_acceptance.py \
  --cov=nex_ag.mvp_acceptance --cov-branch --cov-report=term-missing
```

Observed verification:

```text
inventory: PASS, requirements=33, duplicate_or_missing=0
focused tests: 19 passed, module statement/branch coverage 100%
aggregate regression: 6183 passed, 1 known warning
statement=74958/75839=98.838328564459%
branch=17510/18160=96.420704845815%
```
