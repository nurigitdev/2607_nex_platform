# syntax=docker/dockerfile:1.7
ARG PYTHON_BASE_IMAGE=python:3.12.13-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2
ARG PYTHON_BUILDER_IMAGE=python:3.12.13-bookworm@sha256:3cd9086bdb30f7c9bc08a3fa621d9842e0d3f6f9291aeb4677e0547817c10b12
ARG RUST_BUILDER_IMAGE=rust:1.99.0-slim-bookworm@sha256:2c3a22f0a5533ea2dd5a16627bc841228151faa2d4de2644ac9987e4a2f1f2fa

FROM ${RUST_BUILDER_IMAGE} AS rust-toolchain

FROM ${PYTHON_BUILDER_IMAGE} AS python-wheel-builder
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
ENV CARGO_HOME=/usr/local/cargo \
    RUSTUP_HOME=/usr/local/rustup \
    PATH=/usr/local/cargo/bin:${PATH}
COPY --from=rust-toolchain /usr/local/cargo /usr/local/cargo
COPY --from=rust-toolchain /usr/local/rustup /usr/local/rustup
COPY deployment/locks/python-production.lock /tmp/python-production.lock
RUN python -m pip wheel --no-deps --require-hashes \
      --wheel-dir /opt/nex-wheels \
      -r /tmp/python-production.lock

FROM ${PYTHON_BASE_IMAGE} AS python-dependencies
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY --from=python-wheel-builder /opt/nex-wheels /opt/nex-wheels
RUN python -m pip install --no-index --no-deps /opt/nex-wheels/* \
    && rm -rf /opt/nex-wheels

FROM python-dependencies AS python-source
ARG NEX_VERSION=unversioned
ARG NEX_REVISION=unknown
ARG NEX_BUILD_INPUTS_DIGEST=unknown
LABEL org.opencontainers.image.title="NeX Platform service runtime" \
      org.opencontainers.image.version="${NEX_VERSION}" \
      org.opencontainers.image.revision="${NEX_REVISION}" \
      io.nex-platform.build-inputs-digest="${NEX_BUILD_INPUTS_DIGEST}"
COPY --chown=65532:65532 services /app/services
COPY --chown=65532:65532 database /app/database
COPY --chown=65532:65532 scripts/db /app/scripts/db
COPY --chown=65532:65532 deployment/security /app/deployment/security
RUN install -d -o 65532 -g 65532 -m 0700 /var/lib/nex-platform/diagnostics
ENV HOME=/tmp
USER 65532:65532

FROM python-source AS oa-runtime
ENV PYTHONPATH=/app/services/_shared:/app/services/nex-oa
RUN python -c "import importlib.util; assert importlib.util.find_spec('nex_oa')"
CMD ["python", "-m", "uvicorn", "nex_oa.main:app", "--host", "0.0.0.0", "--port", "8101"]

FROM python-source AS ae-runtime
COPY --chown=65532:65532 domains/mybee/mybee_ax /app/domains/mybee/mybee_ax
ENV PYTHONPATH=/app/services/_shared:/app/services/nex-ae-api:/app/domains/mybee
RUN python -c "import importlib.util; assert importlib.util.find_spec('nex_ae_api'); assert importlib.util.find_spec('mybee_ax')"
CMD ["python", "-m", "uvicorn", "nex_ae_api.main:app", "--host", "0.0.0.0", "--port", "8103"]

FROM ae-runtime AS ae-product-runtime
USER 0:0
COPY --chown=65532:65532 deployment/product/wheel/nex_skill_language-0.2.1-py3-none-any.whl /app/deployment/product/wheel/nex_skill_language-0.2.1-py3-none-any.whl
RUN python -m pip install --no-index --no-deps /app/deployment/product/wheel/nex_skill_language-0.2.1-py3-none-any.whl
COPY --chown=65532:65532 deployment/locks /app/deployment/product/repository/deployment/locks
COPY --chown=65532:65532 deployment/environments /app/deployment/product/repository/deployment/environments
COPY --chown=65532:65532 deployment/product/config /app/deployment/product/config
COPY --chown=65532:65532 domains/mybee/skills /app/deployment/product/repository/domains/mybee/skills
COPY --chown=65532:65532 domains/mybee/catalog /app/deployment/product/repository/domains/mybee/catalog
COPY --chown=65532:65532 contracts/admissions /app/deployment/product/repository/contracts/admissions
COPY --chown=65532:65532 contracts/openapi /app/deployment/product/repository/contracts/openapi
COPY --chown=65532:65532 contracts/schemas/service/nex_eos /app/deployment/product/repository/contracts/schemas/service/nex_eos
COPY --chown=65532:65532 domains/mybee/skills /app/domains/mybee/skills
COPY --chown=65532:65532 contracts /app/contracts
RUN install -d -o 65532 -g 65532 -m 0700 /var/lib/nex-platform/ae-runtime/nsl
ENV NEX_AE_PRODUCT_RUNTIME_PROFILE=VERIFIED_PRODUCT_RELEASE \
    NEX_AE_PRODUCT_REPOSITORY_ROOT=/app/deployment/product/repository \
    NEX_AE_M1_REPOSITORY_ROOT=/app/deployment/product/repository \
    NEX_AE_M1_SIGNED_SKILL_LOCK=/app/deployment/product/repository/deployment/locks/ae-mybee-m1-signed-skill-checkpoint.v3.json \
    NEX_AE_M1_SIGNED_PACKAGE_PATH=/app/deployment/product/repository/domains/mybee/skills/m1_checkpoint/mybee-m1-d04-d12.v3.nsp \
    NEX_AE_PRODUCT_RUNTIME_ADMISSION_PATH=/app/deployment/product/repository/deployment/locks/ae-mybee-m1-runtime-admission.v4.json \
    NEX_AE_PRODUCT_RUNTIME_ACTIVATION_PATH=/app/deployment/product/repository/deployment/locks/ae-mybee-m1-runtime-activation.v4.json \
    NEX_AE_PRODUCT_COORDINATOR_ACTIVATION_PATH=/app/deployment/product/repository/deployment/locks/ae-mybee-m1-product-coordinator-activation.v3.json \
    NEX_AE_PRODUCT_COORDINATOR_ROLLBACK_PATH=/app/deployment/product/repository/deployment/locks/ae-mybee-m1-product-coordinator-rollback.v3.json \
    NEX_AE_PRODUCT_TOOL_CATALOG_PATH=/app/deployment/product/repository/domains/mybee/skills/m1_checkpoint/tool_catalog.v1.json \
    NEX_AE_PRODUCT_RUNTIME_CONTEXT_PATH=/app/deployment/product/repository/domains/mybee/skills/m1_checkpoint/context.json \
    NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH=/app/deployment/product/repository/deployment/environments/ae-product-capability-registry.mybee-m1.v4.json \
    NEX_AE_NSL_WHEEL=/app/deployment/product/wheel/nex_skill_language-0.2.1-py3-none-any.whl \
    NEX_AE_AGENT_WORKER_NSL_WHEEL_LOCK=/app/deployment/product/repository/deployment/locks/nsl-v0.2.1-wheel.json \
    NEX_AE_NSL_PLATFORM_LOCK=/app/deployment/product/repository/deployment/locks/python-production.lock
USER 65532:65532
RUN python -c "import mybee_ax, nsl; from nex_ae_api.agent_runtime_process import build_source_check; from nex_ae_api.mybee_product_admission import require_mybee_product_package; assert nsl.__version__ == '0.2.1'; assert mybee_ax.PACKAGE_VERSION == '0.1.0'; assert require_mybee_product_package()['status'] == 'PASS'; assert build_source_check()['status'] == 'PASS'"

FROM python-source AS cx-runtime
ENV PYTHONPATH=/app/services/_shared:/app/services/nex-cx
RUN python -c "import importlib.util; assert importlib.util.find_spec('nex_cx')"
CMD ["python", "-m", "uvicorn", "nex_cx.main:app", "--host", "0.0.0.0", "--port", "8104"]

FROM python-source AS mo-runtime
ENV PYTHONPATH=/app/services/_shared:/app/services/nex-mo
RUN python -c "import importlib.util; assert importlib.util.find_spec('nex_mo')"
CMD ["python", "-m", "uvicorn", "nex_mo.main:app", "--host", "0.0.0.0", "--port", "8105"]

FROM python-source AS ag-runtime
ENV PYTHONPATH=/app/services/_shared:/app/services/nex-ag
RUN python -c "import importlib.util; assert importlib.util.find_spec('nex_ag')"
CMD ["python", "-m", "uvicorn", "nex_ag.main:app", "--host", "0.0.0.0", "--port", "8102"]

FROM python-source AS wc-runtime
ENV PYTHONPATH=/app/services/_shared:/app/services/nex-wc
RUN python -c "import importlib.util; assert importlib.util.find_spec('nex_wc')"
CMD ["python", "-m", "uvicorn", "nex_wc.main:app", "--host", "0.0.0.0", "--port", "8106"]

FROM python-source AS eos-runtime
ENV PYTHONPATH=/app/services/_shared:/app/services/nex-eos
RUN python -c "import importlib.util; assert importlib.util.find_spec('nex_eos')"
CMD ["python", "-m", "uvicorn", "nex_eos.main:app", "--host", "0.0.0.0", "--port", "8107"]

FROM python-source AS wa-runtime
ENV PYTHONPATH=/app/services/_shared:/app/services/nex-wa
RUN python -c "import importlib.util; assert importlib.util.find_spec('nex_wa')"
CMD ["python", "-m", "uvicorn", "nex_wa.main:app", "--host", "0.0.0.0", "--port", "8108"]
