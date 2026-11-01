# GB2-CA00-S20B Product Trust and Approval Boundary Hardening

## Status

```text
Slice                         = GB2-CA00-S20B
Status                        = CLOSED
Product code change           = NONE
Database migration            = NONE
Public API contract change    = NONE
Remote model provider         = NOT REQUIRED
Slice Gate                    = PASS
```

## Purpose

S20B closes deterministic denial and malformed-input branches in the active
NSL runtime bundle admission and AE/EOS approval-delivery boundaries. The
implementation preserves the existing fail-closed product behavior and adds
tests rather than changing already-correct runtime code.

## Source Audit

The source-backed audit covered:

```text
services/_shared/nex_runtime/nsl_runtime_bundle.py
services/nex-eos/nex_eos/approval_decision_api.py
services/nex-ae-api/nex_ae_api/approval_decision_event_api.py
```

The remaining branches were deterministic validation and exception-mapping
paths. No structural refactoring, database migration, remote provider, or API
shape change was justified.

## Hardening Coverage

The focused regression now verifies:

- unreadable, non-object, extra-field, wrong-schema, and malformed NSL bundle
  manifests;
- invalid nested mappings, bounded text, relative paths, lowercase SHA-256,
  RFC3339 UTC timestamps, path containment, missing artifacts, and digest
  drift;
- EOS service authentication, caller/configuration denial, malformed approval
  delivery, tenant/work-item/decision lineage, resume target UUID, and typed
  transition failure mapping;
- AE NSL approval domain separation, incomplete persisted lineage, bound
  evidence/resume event construction, unavailable admission, and typed event
  failure mapping.

No test bypasses the production admission functions.

## Verification

Focused regression:

```text
tests/test_gb2_ca00_s20b_trust_approval_boundaries.py
  26 passed

related approval/runtime regression
  89 passed

ruff check
  PASS

compileall
  PASS
```

The first Slice Gate attempt showed that the `platform` profile discovers
`test_platform_*` automatically but does not own existing
`test_nex_platform_*` approval regressions. The final Gate explicitly included
the two existing owner tests; no coverage threshold was lowered.

Final Slice Gate:

```text
pytest                                      = 475 passed / 8 protected skips
nsl_runtime_bundle.py statement / branch   = 100.00% / 100.00%
approval_decision_api.py statement / branch = 100.00% / 100.00%
approval_decision_event_api.py statement / branch
                                            = 100.00% / 100.00%
contract validation                         = PASS (227 / 291 / 245 / 10)
Golden Journey transition audit             = PASS
Demo-to-Product dependency audit            = PASS
Slice Gate exit code                        = 0
```

Protected skips are PostgreSQL topology/trust/restart tests unrelated to the
deterministic S20B claims. No remote generation, embedding, or reranker
provider is required by this Slice.

## Decision

GB2-CA00-S20B is closed. The next Slice is `GB2-CA00-S20C: WC Durable
Coordination and Work-Result Hardening`.
