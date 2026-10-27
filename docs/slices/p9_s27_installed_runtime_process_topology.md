# P9-S27: Installed Runtime / Process Topology

## Scope

The P9 Compose topology now activates both installed NeX-WA processes:

```text
nex-wa
nex-wa-evidence-consumer
```

The consumer is no longer a readiness-only profile. Its packaged command is
`python -m nex_wa.consumer_main`, its capability is `job_claiming`, and Compose
supervises it with `restart: unless-stopped`. It remains internal, non-root,
read-only, without a host port, and receives only owner-scoped OpenBao secret
references through the production container bootstrap.

## Runtime Composition

The installed process reuses the existing WA PostgreSQL JobQueue, fencing,
stale recovery, heartbeat, service log, operational event, admission, and
source adapter implementations. It adds no queue or business-state authority.

Startup resolves the four outbound service edges with minimum scopes:

| Audience | Scopes |
|---|---|
| `nex-ae-api` | `service:call`, `work:source:read` |
| `nex-wc` | `service:call`, `work:source:read` |
| `nex-oa` | `service:call`, `identity:subject:verify` |
| `nex-eos` | `service:call`, `project:verify` |

The process fails closed when persistence, migration, source-adapter,
endpoint, token, or worker identity admission fails. Startup recovers stale
claims before polling. SIGINT/SIGTERM and external supervisor stops dispose
both pools and leave the durable heartbeat in `STOPPED` state. Error output is
metadata-only and does not expose database or token details.

## Protected Evidence

- actual `nex_wa_test` identity: `nex_wa_test / nex_wa_user`
- migration current, idle polling, graceful stop, same-worker restart: `PASS`
- worker heartbeat after both runs: `STOPPED / wa.evidence_consumer`
- scoped service-log and heartbeat cleanup: zero residue
- owner-scoped WA OCI context: `153` files, `1,676,795` bytes
- actual image: `nex-platform-local/nex-wa-runtime:p9-s27`
- image ID: `sha256:8049b21cddf7bb761632966a9c449eb4b4c899e1baf0add19812f43cf9d56c2a`
- runtime user: `65532:65532`
- read-only/network-none container entrypoint check: `PASS`
- merged S143 + S146 + P8 Demo + P9 WA Compose render: `PASS`

No registry push or remote model-provider call was performed.

## Quality Evidence

- deployment/runtime focused regression: `107 passed`
- S27 focused regression: `40 passed`, one protected smoke skipped by default
- protected PostgreSQL smoke: `1 passed`
- NeX-WA Slice Gate: `301 passed`, `12` protected skips
- statement coverage: `97.17%` against P9 floor `96%`
- branch coverage: `94.49%` against P9 floor `94%`
- contracts: `226` schemas, `290` examples, `241` negative examples, `10`
  OpenAPI documents
- `git diff --check`: `PASS`
