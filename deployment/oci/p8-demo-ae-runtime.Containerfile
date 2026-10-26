# syntax=docker/dockerfile:1.7
ARG NEX_AE_BASE_RUNTIME_IMAGE
FROM ${NEX_AE_BASE_RUNTIME_IMAGE}

USER 0:0
COPY --chown=65532:65532 wheel/nex_skill_language-0.2.1-py3-none-any.whl /app/deployment/p8-demo/wheel/nex_skill_language-0.2.1-py3-none-any.whl
RUN python -m pip install --no-deps /app/deployment/p8-demo/wheel/nex_skill_language-0.2.1-py3-none-any.whl

COPY --chown=65532:65532 skill /app/deployment/p8-demo/nsl/golden_a_voucher_draft
COPY --chown=65532:65532 fixtures /app/deployment/p8-demo/fixtures
COPY --chown=65532:65532 locks /app/deployment/p8-demo/locks
RUN install -d -o 65532 -g 65532 -m 0700 /var/lib/nex-platform/ae-runtime/nsl

ENV NEX_AE_DEMO_NSL_BUNDLE_MANIFEST=/app/deployment/p8-demo/locks/p8-demo-nsl-runtime-bundle.v1.json \
    NEX_AE_DEMO_NSL_WHEEL=/app/deployment/p8-demo/wheel/nex_skill_language-0.2.1-py3-none-any.whl \
    NEX_AE_AGENT_WORKER_NSL_WHEEL_LOCK=/app/deployment/p8-demo/locks/nsl-v0.2.1-wheel.json \
    NEX_AE_DEMO_PLATFORM_LOCK=/app/deployment/p8-demo/locks/python-production.lock \
    NEX_AE_DEMO_NSL_SKILL_ROOT=/app/deployment/p8-demo/nsl/golden_a_voucher_draft \
    NEX_AE_DEMO_FIXTURE=/app/deployment/p8-demo/fixtures/p8_demo_vo00_fixture.v1.json \
    NEX_AE_DEMO_BASE_FIXTURE=/app/deployment/p8-demo/fixtures/p8_golden_a_fixture.v1.json

USER 65532:65532
RUN python -c "import os; from pathlib import Path; names=('NEX_AE_DEMO_NSL_BUNDLE_MANIFEST','NEX_AE_DEMO_NSL_WHEEL','NEX_AE_AGENT_WORKER_NSL_WHEEL_LOCK','NEX_AE_DEMO_PLATFORM_LOCK','NEX_AE_DEMO_NSL_SKILL_ROOT','NEX_AE_DEMO_FIXTURE','NEX_AE_DEMO_BASE_FIXTURE'); assert all(Path(os.environ[name]).exists() for name in names)"
RUN python -c "import nsl; from nex_ae_api.demo_runtime import build_source_check; assert nsl.__version__ == '0.2.1'; assert build_source_check()['status'] == 'PASS'"
