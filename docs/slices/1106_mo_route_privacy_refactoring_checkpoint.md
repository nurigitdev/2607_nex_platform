# Slice 1106: MO route privacy refactoring checkpoint

## Goal

Repair the high-risk MO public profile projection without removing model paths
from the internal runtime catalog or changing CX-facing execution APIs.

## Result

- Internal `ModelProfile.model_path` values remain available to MO runtime
  composition.
- Public provider-profile rows no longer expose `model_path` or deprecated
  `live_health_env` names.
- Provider-profile response metadata no longer exposes `model_root`.
- The embedding model identity is canonicalized to `Qwen3-Embedding-4B` across
  the default catalog, preflight request, tests, and examples.
- The closed JSON Schema removes private fields and a dedicated negative fixture
  proves `model_path` is rejected.
- Four lower-risk catalog/configuration drift findings remain ordered for S112:
  stable live aliases, legacy env metadata, and strict provider-mode validation.
- No table or migration is added.

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_mo_profile_privacy_refactor_checkpoint.py --summary

./.venv/bin/pytest -q \
  tests/test_mo_profile_privacy_refactor_checkpoint.py \
  tests/test_nex_mo_providers.py \
  tests/test_dgx_live_provider_preflight.py \
  --cov=nex_mo.profile_privacy_audit \
  --cov=nex_mo.providers \
  --cov-branch --cov-report=term-missing
```

Observed verification:

```text
focused tests: 72 passed
Slice Gate: 238 passed, 1 known warning
MO statement coverage: 99.64%
MO branch coverage: 98.34%
Checkpoint Gate: 8,411 passed, 5 protected smoke skipped, 123 warnings
aggregate statement coverage: 98.72%
aggregate branch coverage: 96.86%
contract validation: 109 schemas, 167 examples, 132 negative examples, 7 OpenAPI
```
