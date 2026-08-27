# Slice 0382: AE-to-CX Repaired Lineage Client Adapter

## Scope

Add the AE-side client adapter that fetches CX remediation execution detail and
the repaired CX generation record needed to build an AE repaired response
handoff.

This slice does not add route wiring, persistence, PostgreSQL smoke, or a user
acceptance workflow. It prepares the safe source package that later slices can
persist and expose.

## Implemented

- Added `HttpCxRepairedResponseSourceClient` in
  `services/nex-ae-api/nex_ae_api/repaired_response_client.py`.
- Added guarded CX reads:
  - `GET /api/v1/generations/{cx_generation_id}/remediation-executions/{remediation_action_id}`;
  - `GET /api/v1/generations/{cx_generation_id}` for the repaired generation.
- Added `ae_cx_repaired_response_source_package.v1`, which keeps only the
  sanitized subset needed by `ae_repaired_response_handoff.v1`.
- Added source-material redaction checks that allow safe usage counters and
  source-shape booleans while rejecting raw prompts, messages, raw generation
  output, source text, provider details, credentials, tokens, database URLs,
  model paths, and storage paths.
- Added environment-driven timeout/client configuration:
  - `NEX_CX_BASE_URL`;
  - `NEX_AE_TO_CX_SERVICE_TOKEN`;
  - `NEX_AE_CX_REPAIRED_RESPONSE_TIMEOUT_SECONDS`.
- Added a bridge helper that builds the final repaired response handoff from a
  validated source package.

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_ae_repaired_response_client.py -q
21 passed in 1.84s
```

Targeted adapter coverage:

```text
./.venv/bin/pytest tests/test_nex_ae_repaired_response_client.py -q --cov=nex_ae_api.repaired_response_client --cov-branch --cov-report=term-missing
services/nex-ae-api/nex_ae_api/repaired_response_client.py statement_coverage=100% branch_coverage=100%
```

Full quality gate:

```text
scripts/quality/run_quality_gate.sh
2765 passed, 1 warning in 78.61s
statement_coverage=98.64% threshold=95.00%
branch_coverage=96.03% threshold=85.00%
contract_validation=pass schemas=60 examples=92 negative_examples=68 openapi=7
s34_feedback_disposition_closure=pass slice_range=0331-0340 required_files=21
s35_remediation_observability_closure=pass slice_range=0341-0350 required_files=26
s36_remediation_execution_closure=pass slice_range=0351-0360 required_files=33
s37_remediation_runtime_integration_closure=pass slice_range=0361-0370 required_files=31
s38_remediation_operations_automation_closure=pass slice_range=0371-0380 required_files=41
```

Recommended next slices:

```text
Slice 0383: AE repaired handoff persistence foundation
Slice 0384: AE repaired handoff service API wiring
Slice 0385: AE repaired handoff PostgreSQL smoke evidence
```
