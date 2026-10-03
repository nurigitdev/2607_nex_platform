# Slice 1275: AE signed-token verification adoption

## Goal

Make NeX-AE the first S128 consumer of the shared signed service-token
admission runtime while preserving browser-user authentication.

## Implementation

- Wired `nex-ae-api` application composition to a profile-driven shared
  admission runtime for audience `nex-ae-api`.
- Routed the central AE facade guard, AE-specific service guards, and shared
  compatibility/prompt/recovery guards through application-owned admission.
- Preserved browser user bearer/session handling. A failed signed service token
  is returned directly and is not retried through the browser-user path.
- Removed direct AE package calls to the legacy mock service-token validator.
- Centralized all AE outbound service-token selection. `TEST_MOCK` can issue an
  explicit test mock; DUAL_READ and SIGNED_ONLY require a configured signed
  token and fail closed when it is absent.
- Updated historical source-shape audits to recognize the stronger S128
  admission boundary instead of the removed mock validator call.

## Environment

Inbound admission uses the Slice 1274 variables. Outbound signed tokens use:

- `NEX_AE_TO_OA_SERVICE_TOKEN`
- `NEX_AE_TO_CX_SERVICE_TOKEN`
- `NEX_AE_TO_MO_SERVICE_TOKEN`
- `NEX_AE_TO_AG_SERVICE_TOKEN`

No database migration or DGX provider is required.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_runtime_service_token_admission.py \
  tests/test_nex_ae_service_token_adoption.py \
  --cov=nex_runtime.service_token_admission \
  --cov-branch \
  --cov-report=term-missing

./scripts/quality/run_slice_gate.sh \
  --service nex-ae-api \
  --test tests/test_nex_runtime_service_token_admission.py \
  --test tests/test_nex_ae_service_token_adoption.py \
  --test tests/test_ae_signed_token_adoption_smoke.py \
  --coverage-target scripts/smoke/run_ae_signed_token_adoption.py \
  --smoke scripts/smoke/run_ae_signed_token_adoption.py
```

The focused command measures the changed shared admission module at 100%.
The AE package is already measured by the service profile. Keeping the shared
module out of the broad AE collection also avoids `pytest-cov` pre-importing
the `nex_runtime` package while test collection initializes SQLAlchemy.
