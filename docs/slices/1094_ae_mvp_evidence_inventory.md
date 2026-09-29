# Slice 1094: AE MVP Evidence Inventory

## Goal

Create one canonical, machine-checkable inventory of the S101 through S109
closure evidence required by AE service MVP acceptance.

## Inventory Rules

- Exactly nine requirements are included, from S101 through S109.
- Every requirement has exactly one closure runner and one closure document.
- Runner and document identity tokens must agree with the requirement and
  closure Slice number.
- Missing, duplicate, unreadable, or identity-mismatched evidence fails closed.
- Repository modification time is not acceptance freshness. Every runtime gate
  supplies a timezone-aware `observed_at`, and the server clock is authoritative.
- The inventory returns relative repository paths and status metadata only. It
  contains no test log, prompt, response, source content, credential, endpoint,
  database URL, or storage path.

## Capability Groups

The inventory covers current-state assurance, durable workspace/chat,
runtime-policy orchestration, asynchronous generation, generation lifecycle,
citation repair, generated-response lineage, asynchronous artifact rendering,
and the grounded-generation Web experience.

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_ae_mvp_evidence_inventory.py \
  --cov=nex_ae_api.mvp_acceptance --cov-branch --cov-report=term-missing
```

The repository inventory resolves nine unique requirements with no issues. No
table or migration is added.
