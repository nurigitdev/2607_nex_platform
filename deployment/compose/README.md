# S143 Single-Host Staging Compose

This deployment profile proves the S143 external secret and managed TLS
boundary on one Docker host. It is deliberately smaller than Kubernetes:
Docker Compose owns process order, OpenBao owns secret and certificate
material, and Traefik owns HTTPS ingress.

## Components

| Component | Source | Host installation |
| --- | --- | --- |
| Docker Engine | Existing host runtime | Required and already present |
| Docker Compose plugin | Existing `docker compose` command | Required and already present |
| OpenBao | Digest-pinned `ghcr.io/openbao/openbao:2.7.1` image | Not required |
| Traefik | Digest-pinned `traefik:3.7.14` image | Not required |
| PostgreSQL | Existing five localhost test databases | Reused through `host.docker.internal` |
| DGX providers | Existing `192.168.20.243:9111-9113` services | Reused through Traefik HTTPS routes |

No Kubernetes, Helm, service mesh, OpenBao Agent sidecars, or host-installed
OpenBao/Traefik packages are required for this staging acceptance. Docker pulls
the two external images automatically. A registry push is not performed.

## Boundary

- Only Traefik publishes `8080` and `8443` on the host.
- OpenBao publishes its administrative TLS endpoint only on
  `127.0.0.1:8200`.
- A network-disabled, one-shot `openbao-data-init` service grants the named
  Raft volume to the image's fixed non-root UID/GID before OpenBao starts. It
  checks the current owner before repair, retains only the `CHOWN` capability,
  and is not a runtime service.
- OpenBao joins the internal `control` network for service access and a
  dedicated `admin` bridge solely so Docker can publish the loopback-bound
  administrative endpoint.
- Five Python service containers authenticate with owner-specific, one-use
  AppRole SecretIDs. Each process resolves only its owner secrets, revokes its
  short-lived OpenBao token, removes all secret references from the child
  environment, and then executes the packaged service command.
- The AE Web image receives no OpenBao credential or database/provider secret.
- OpenBao uses integrated Raft storage. Traefik uses the file provider and does
  not mount the Docker socket.
- Platform and provider URLs are HTTPS. DGX remains HTTP on the trusted
  upstream side of Traefik for this non-production staging profile.
- Runtime credentials, bootstrap keys, and private keys are generated under a
  mode-`0700` runtime directory and are never committed or written to reports.

## Protected Acceptance

The runner requires explicit opt-in and eight protected inputs: five test
database URLs and the three current DGX API keys. It performs current test DB
migration readiness, builds the OpenBao KV/AppRole/PKI state, starts the six
application images, verifies all service readiness and three live provider
routes, rotates all sixteen secret versions, renews TLS, and proves both secret
and certificate rollback.

```bash
NEX_S143_EXTERNAL_STAGING_ACCEPTANCE=1 \
NEX_OA_TEST_DATABASE_URL='...' \
NEX_AG_TEST_DATABASE_URL='...' \
NEX_AE_TEST_DATABASE_URL='...' \
NEX_CX_TEST_DATABASE_URL='...' \
NEX_MO_TEST_DATABASE_URL='...' \
NEX_MO_REMOTE_EMBEDDING_API_KEY='...' \
NEX_MO_REMOTE_RERANKER_API_KEY='...' \
NEX_MO_VLLM_API_KEY='...' \
./.venv/bin/python scripts/smoke/run_s143_external_staging_acceptance.py \
  --execute --summary
```

The runner uses a temporary runtime directory and always executes
`docker compose down --volumes --remove-orphans`. A persistent staging
installation may instead prepare an operator-controlled directory under
`/data/nex-platform/staging`, but its bootstrap and unseal material must remain
outside the repository and backup policy belongs to S145.

## S144 Trust and Federation Override

S144 keeps the S143 base file immutable and layers
`s144-staging.override.yaml` on top. The override enables the OpenBao browser
authorization UI, routes `id.nex-staging.test` through Traefik with verified
OpenBao TLS, selects OA's Transit signer, and supplies the exact enterprise
OIDC policy. OpenBao generates the public client ID during protected setup; it
must be passed to Compose without writing the client secret to an environment
file.

```bash
NEX_S144_OIDC_CLIENT_ID='OpenBao-generated-public-id' \
docker compose \
  -f deployment/compose/s143-staging.compose.yaml \
  -f deployment/compose/s144-staging.override.yaml \
  config --quiet
```

The client secret stays in OpenBao KV, the OA AppRole retains owner-only KV
read plus exact Transit sign/read permissions, and the separate bootstrap
administrator remains the only principal allowed to create or rotate keys and
OIDC resources. No Kubernetes, host OpenBao/Traefik package, Docker socket
mount, or privileged application container is introduced.
