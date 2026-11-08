# syntax=docker/dockerfile:1.7
ARG NODE_BASE_IMAGE=node:22-bookworm-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392

FROM ${NODE_BASE_IMAGE} AS ae-web-build
WORKDIR /build/apps/nex-ae-web
COPY apps/nex-ae-web/package.json apps/nex-ae-web/package-lock.json ./
RUN npm ci --ignore-scripts
COPY apps/nex-ae-web/modern.html apps/nex-ae-web/vite.config.ts apps/nex-ae-web/tsconfig.json ./
COPY apps/nex-ae-web/src ./src
COPY apps/nex-ae-web/scripts/promoteModernBuild.mjs ./scripts/promoteModernBuild.mjs
RUN npm run build:v2 \
    && npm cache clean --force

FROM ${NODE_BASE_IMAGE} AS ae-web
ARG NEX_VERSION=unversioned
ARG NEX_REVISION=unknown
ARG NEX_BUILD_INPUTS_DIGEST=unknown
LABEL org.opencontainers.image.title="NeX AE Web" \
      org.opencontainers.image.version="${NEX_VERSION}" \
      org.opencontainers.image.revision="${NEX_REVISION}" \
      io.nex-platform.build-inputs-digest="${NEX_BUILD_INPUTS_DIGEST}"
WORKDIR /app
COPY --from=ae-web-build --chown=node:node /build/apps/nex-ae-web/dist ./dist
COPY --chown=node:node apps/nex-ae-web/scripts/serve.mjs ./scripts/serve.mjs
ENV HOST=0.0.0.0 \
    PORT=5173 \
    NODE_ENV=production \
    NEX_AE_WEB_STATIC_ROOT=/app/dist
USER node
ENTRYPOINT []
CMD ["node", "scripts/serve.mjs"]
