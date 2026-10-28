# syntax=docker/dockerfile:1.7
ARG NEX_AE_BASE_RUNTIME_IMAGE
FROM ${NEX_AE_BASE_RUNTIME_IMAGE}

USER 0:0
COPY --chown=65532:65532 wheel/nex_skill_language-0.2.1-py3-none-any.whl /app/deployment/product/wheel/nex_skill_language-0.2.1-py3-none-any.whl
RUN python -m pip install --no-deps /app/deployment/product/wheel/nex_skill_language-0.2.1-py3-none-any.whl

COPY --chown=65532:65532 skill /app/deployment/product/nsl/finance_voucher_draft_create
COPY --chown=65532:65532 config /app/deployment/product/config
COPY --chown=65532:65532 locks /app/deployment/product/locks
RUN install -d -o 65532 -g 65532 -m 0700 /var/lib/nex-platform/ae-runtime/nsl

ENV NEX_AE_NSL_BUNDLE_MANIFEST=/app/deployment/product/locks/ae-product-nsl-runtime-bundle.v1.json \
    NEX_AE_NSL_WHEEL=/app/deployment/product/wheel/nex_skill_language-0.2.1-py3-none-any.whl \
    NEX_AE_AGENT_WORKER_NSL_WHEEL_LOCK=/app/deployment/product/locks/nsl-v0.2.1-wheel.json \
    NEX_AE_NSL_PLATFORM_LOCK=/app/deployment/product/locks/python-production.lock \
    NEX_AE_NSL_SKILL_ROOT=/app/deployment/product/nsl/finance_voucher_draft_create \
    NEX_AE_FINANCE_GOLDEN_A_AUTHORITY_PROFILE_PATH=/app/deployment/product/config/finance-golden-a-vo00.v1.json \
    NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH=/app/deployment/product/config/ae-product-capability-registry.v1.json

USER 65532:65532
RUN python -c "import os; from pathlib import Path; names=('NEX_AE_NSL_BUNDLE_MANIFEST','NEX_AE_NSL_WHEEL','NEX_AE_AGENT_WORKER_NSL_WHEEL_LOCK','NEX_AE_NSL_PLATFORM_LOCK','NEX_AE_NSL_SKILL_ROOT','NEX_AE_FINANCE_GOLDEN_A_AUTHORITY_PROFILE_PATH','NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH'); assert all(Path(os.environ[name]).exists() for name in names)"
RUN python -c "import nsl; from nex_ae_api.agent_runtime_process import build_source_check; assert nsl.__version__ == '0.2.1'; assert build_source_check()['status'] == 'PASS'"
