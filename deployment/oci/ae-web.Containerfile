# syntax=docker/dockerfile:1.7
ARG NODE_BASE_IMAGE=node:22-bookworm-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392

FROM ${NODE_BASE_IMAGE} AS ae-web
ARG NEX_VERSION=unversioned
ARG NEX_REVISION=unknown
ARG NEX_BUILD_INPUTS_DIGEST=unknown
LABEL org.opencontainers.image.title="NeX AE Web" \
      org.opencontainers.image.version="${NEX_VERSION}" \
      org.opencontainers.image.revision="${NEX_REVISION}" \
      io.nex-platform.build-inputs-digest="${NEX_BUILD_INPUTS_DIGEST}"
WORKDIR /app/apps/nex-ae-web
COPY --chown=node:node apps/nex-ae-web/package.json apps/nex-ae-web/package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts \
    && npm cache clean --force
COPY --chown=node:node apps/nex-ae-web/index.html ./index.html
COPY --chown=node:node apps/nex-ae-web/src ./src
COPY --chown=node:node apps/nex-ae-web/scripts/serve.mjs ./scripts/serve.mjs
ENV HOST=0.0.0.0 \
    PORT=5173 \
    NODE_ENV=production
USER node
ENTRYPOINT []
CMD ["npm", "start", "--silent"]
