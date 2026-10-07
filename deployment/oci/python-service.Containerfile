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
ENV HOME=/tmp
USER 65532:65532

FROM python-source AS oa-runtime
ENV PYTHONPATH=/app/services/_shared:/app/services/nex-oa
RUN python -c "import importlib.util; assert importlib.util.find_spec('nex_oa')"
CMD ["python", "-m", "uvicorn", "nex_oa.main:app", "--host", "0.0.0.0", "--port", "8101"]

FROM python-source AS ae-runtime
ENV PYTHONPATH=/app/services/_shared:/app/services/nex-ae-api
RUN python -c "import importlib.util; assert importlib.util.find_spec('nex_ae_api')"
CMD ["python", "-m", "uvicorn", "nex_ae_api.main:app", "--host", "0.0.0.0", "--port", "8103"]

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
