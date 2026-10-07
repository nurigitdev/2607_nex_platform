# syntax=docker/dockerfile:1.7
ARG PYTHON_BASE_IMAGE=python:3.12.13-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2

FROM ${PYTHON_BASE_IMAGE} AS python-dependencies
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY deployment/locks/python-production.lock /tmp/python-production.lock
RUN python -m pip install --no-deps --require-hashes -r /tmp/python-production.lock \
    && rm /tmp/python-production.lock

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
CMD ["uvicorn", "nex_oa.main:app", "--host", "0.0.0.0", "--port", "8101"]

FROM python-source AS ae-runtime
ENV PYTHONPATH=/app/services/_shared:/app/services/nex-ae-api
RUN python -c "import importlib.util; assert importlib.util.find_spec('nex_ae_api')"
CMD ["uvicorn", "nex_ae_api.main:app", "--host", "0.0.0.0", "--port", "8103"]

FROM python-source AS cx-runtime
ENV PYTHONPATH=/app/services/_shared:/app/services/nex-cx
RUN python -c "import importlib.util; assert importlib.util.find_spec('nex_cx')"
CMD ["uvicorn", "nex_cx.main:app", "--host", "0.0.0.0", "--port", "8104"]

FROM python-source AS mo-runtime
ENV PYTHONPATH=/app/services/_shared:/app/services/nex-mo
RUN python -c "import importlib.util; assert importlib.util.find_spec('nex_mo')"
CMD ["uvicorn", "nex_mo.main:app", "--host", "0.0.0.0", "--port", "8105"]

FROM python-source AS ag-runtime
ENV PYTHONPATH=/app/services/_shared:/app/services/nex-ag
RUN python -c "import importlib.util; assert importlib.util.find_spec('nex_ag')"
CMD ["uvicorn", "nex_ag.main:app", "--host", "0.0.0.0", "--port", "8102"]

