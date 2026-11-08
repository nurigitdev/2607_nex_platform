# P9-S25: Service Trust, Deployment, and Registry Hardening

## Scope

The promoted P9 runtime profile now requires the five WA trust edges in
addition to the frozen S142/P8 trust inventory:

```text
AE -> WA
WA -> AE
WA -> WC
WA -> OA
WA -> EOS
```

The P8 deployment files remain historical baselines. The additive
`p9-wa.override.yaml` defines the ninth immutable image, WA API on internal
port `8108`, managed TLS ingress, owner-scoped OpenBao references, non-root
production bootstrap, read-only filesystem, `/tmp` tmpfs, `cap_drop: ALL`,
`no-new-privileges`, and no direct host application port.

`P9_WA` is an additive production-bootstrap boundary. `nex-ae-api` inherits
its complete P8 Demo owner-local secret inventory and adds only
`NEX_AE_TO_WA_SERVICE_TOKEN`; `nex-wa` materializes its database URL and four
outbound service tokens. Raw values, cross-owner references, invalid versions,
and resolver metadata drift fail closed. Secret references and AppRole inputs
are removed before the application process is executed.

## Consumer Boundary

The Compose override exposes `nex-wa-evidence-consumer` only under the
`p9-wa-readiness` profile and runs `--check`. The currently packaged generic
background shell does not claim WA Jobs, so S25 does not present it as an
active consumer. P9-S27 owns installed work-claiming activation.

## Verification

- exact current-profile trust inventory and fail-closed required inputs
- WA OCI/process registry retained from P9-S01A
- Compose source security and owner-scoped secret-reference scan
- P9 WA OpenBao materialization, owner isolation, and bootstrap scrub/revoke
- Traefik managed TLS route and internal `8108` upstream
- NeX-WA Slice Gate
- P9 Checkpoint Gate #3 after this Slice

## Evidence

- production bootstrap and trust focused regression: `49 passed`
- merged 9-image Compose configuration render: `PASS`
- NeX-WA Slice Gate: `278 passed`, `10 skipped`
- NeX-WA statement coverage: `97.13%`
- NeX-WA branch coverage: `94.06%`
- P9 Checkpoint Gate #3: `17,508 passed`, `128 skipped`
- repository statement coverage: `98.17%`
- repository branch coverage: `96.62%`
- contract validation: `226` schemas, `290` examples, `241` negative
  examples, and `10` OpenAPI documents
