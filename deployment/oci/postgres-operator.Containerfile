# syntax=docker/dockerfile:1.7
ARG NEX_PYTHON_RUNTIME_IMAGE
ARG POSTGRES_BASE_IMAGE=postgres:16.9-bookworm@sha256:253815cf7579ffa05e1673d92e78d37273e61be0e4414e9a1449337d7925be94

FROM ${NEX_PYTHON_RUNTIME_IMAGE} AS python-runtime

FROM ${POSTGRES_BASE_IMAGE} AS postgres-operator
ARG NEX_VERSION=unversioned
ARG NEX_REVISION=unknown
LABEL org.opencontainers.image.title="NeX PostgreSQL recovery operator" \
      org.opencontainers.image.version="${NEX_VERSION}" \
      org.opencontainers.image.revision="${NEX_REVISION}" \
      io.nex-platform.artifact-class="postgres-recovery-tool"
COPY --from=python-runtime /usr/local /usr/local
WORKDIR /app
COPY --chown=65532:65532 services/_shared /app/services/_shared
COPY --chown=65532:65532 scripts/db /app/scripts/db
COPY --chown=65532:65532 deployment/postgres /app/deployment/postgres
ENV HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/services/_shared:/app/scripts/db
USER 65532:65532
ENTRYPOINT ["python", "/app/scripts/db/run_postgres_backup_operator.py"]
CMD ["--check", "--summary"]
