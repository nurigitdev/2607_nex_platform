# P8-DEMO-S07: Compose and Traefik Demo Topology

## Outcome

The P8 Demo release now has an additive single-host Compose overlay. Historical
S143 and S146 sources remain unchanged. The rendered topology contains:

```text
7 backend APIs
1 AE Web
3 required background processes
OpenBao + one-shot data init
Traefik
RustFS
```

The eleven installed application processes consume the exact eight-image S06
release set. AE, WC, and EOS workers reuse their owner image.

## Routing and Isolation

`deployment/compose/traefik/p8-demo-dynamic.yaml` preserves the existing
service/provider/object routes and adds TLS routes for:

```text
wc.nex-staging.test  -> nex-wc:8106
eos.nex-staging.test -> nex-eos:8107
```

Only Traefik publishes application ingress. WC, EOS, all workers, PostgreSQL,
and RustFS expose no direct host application port. The Demo overlay supplies
the internal identity network required when S146 is used without the optional
S144 federation overlay.

## Trust Inputs

The overlay declares owner-specific WC/EOS AppRole files, dev database secret
references, and the AE/WC/EOS cross-service token references. It contains no
credential value and no `*_TEST_DATABASE_URL`. OpenBao policy creation and
secret materialization are intentionally owned by P8-DEMO-S08.

## Protected Render Evidence

The S06 OCI report supplies all eight immutable image references. The protected
runner executes the real Docker Compose parser over:

```text
s143-staging.compose.yaml
s146-object-storage.override.yaml
p8-demo.override.yaml
```

Observed result:

```text
status = PASS
rendered services = 15
installed application processes = 11
immutable application images = 8
secret included = false
database URL included = false
```

Static admission and rendered admission both fail closed on missing processes,
mutable/partial images, worker host ports, weakened restart policy, raw/test DB
inputs, route drift, and owner-secret omissions.

P8-DEMO-S07 closes topology rendering. P8-DEMO-S08 may now materialize and
rotate the owner-scoped OpenBao secrets required to start it.
