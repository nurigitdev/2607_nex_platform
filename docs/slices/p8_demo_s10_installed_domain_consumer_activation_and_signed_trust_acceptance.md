# P8-DEMO-S10: Installed Domain Consumer Activation and Signed Trust Acceptance

## Outcome

The installed Chairman Demo topology now activates the existing P6-P8 domain
composition. This Slice adds no replacement scheduler, worker, approval flow,
controlled WRITE path, or business behavior.

```text
composition mode          = EXISTING_COMPONENT_COMPOSITION
domain consumers          = 3
signed runtime admissions = 4
mock token admissions     = 0
new business behavior     = false
status                    = PASS
```

The admitted consumers are:

```text
nex-ae-agent-runtime-worker
nex-wc-event-delivery-worker
nex-eos-outbox-publisher
```

## Installed Trust Boundary

The Demo AppRole profile is bounded to the `staging_live` / `P8_DEMO`
deployment boundary. It uses a 24-hour Secret ID TTL and unlimited uses so an
API and its owner-scoped worker can re-authenticate after restart. Startup
issues 24-hour audience-scoped signed service tokens from OA; no token or
client-secret value is written to evidence.

OA now exposes the same protected runtime-admission route as the other
services. The exact installed acceptance proves signed-only admission for OA,
AE, WC, and EOS and reports all four services `READY`. WC and EOS are admitted
as OA service-principal service IDs by migration
`2516_oa_service_principal_wc_eos.sql`.

The one-year service-token proposal remains deferred. The Demo profile is a
bounded startup bootstrap, not the production credential lifecycle.

## OCI and Runtime Evidence

The actual local image set was rebuilt from source revision
`61b9522e5413867864463d43608e3703f7bd9b9e` without registry push.

```text
application images        = 8 / 8
release set digest        = sha256:92d8979035ccf578681a71f13e575aeea06afdbf4c0c94215df94fe15d70038f
AE installed image        = nex-platform-demo/nex-ae-runtime@sha256:ec29d67462696d31d71eea471018a80a11f516c28ad558155618a3d21d7b4316
runtime user              = non-root
packaged process checks   = PASS
```

The Compose admission converts the locally built artifact identities to real
immutable repository digests. Synthetic or mutable image references, missing
artifacts, digest drift, and installed AE repository drift fail closed. The AE
image also verifies all seven embedded NSL/runtime assets required by the
existing composition.

## Actual Protected Acceptance

The protected runner used the actual local Docker engine, OpenBao, Traefik,
RustFS boundary, and all seven admitted development PostgreSQL databases.
Fresh backups preceded the two migration changes needed by S10:

```text
backup 1                  = 20261026T011025Z-aebf0df941f653aa
backup 2                  = 20261026T011630Z-43c603079cfb0cb2
OA migrations             = 19 / 19
AG migrations             = 20 / 20
AE migrations             = 61 / 61
CX migrations             = 23 / 23
MO migrations             = 10 / 10
WC migrations             = 13 / 13
EOS migrations            = 16 / 16
```

All three consumers started with the packaged command, authenticated through
OpenBao, bootstrapped signed service tokens, emitted a heartbeat, stopped, and
restarted. The second process generation repeated startup-token bootstrap and
renewed every heartbeat. Queue counts remained zero before activation and
after restart, proving that the empty Demo state was not mutated merely by
consumer activation.

Generation, embedding, and reranking providers were not contacted because
this Slice admits installed consumers and signed trust only. Live provider
admission remains the independently passed P8-DEMO-S09 boundary.

## Cleanup and Privacy

The runner removed the ephemeral Compose project and deleted every temporary
OA trust row in a `finally` boundary. A direct post-run query confirmed:

```text
P8 Demo service principals = 0
P8 Demo credentials        = 0
P8 Demo signing keys       = 0
S10 Compose containers     = 0
secret/token values        = absent from report
```

Evidence is recorded in ignored runtime reports:

- `reports/deployment/p8-demo-s10-installed-domain.json`
- `reports/deployment/p8-demo-oci-image-build.json`
- `reports/deployment/p8-demo-ae-runtime-image.json`
- `reports/quality/p8-demo-s10-slice.coverage.json`

## Regression and Coverage

The initial broad `nex-runtime` Gate executed `1,868` tests successfully but
exposed that the profile measures unrelated historical shared modules and is
not a valid changed-scope coverage boundary. The platform changed-scope Gate
then found a real stale S141 loopback baseline. It was hardened from two
aggregate constants to an exact source-backed per-file inventory, so future
unapproved additions and removals still fail closed.

The final Slice Gate result is:

```text
tests                     = 462 passed / 6 protected skips
statement coverage        = 98.78% / required 95.00%
branch coverage           = 96.85% / required 94.00%
demo_domain_installation  = 98.41% statement / 96.15% branch
demo_compose              = 99.35% statement / 98.75% branch
service_token_admission   = 98.61% statement / 95.69% branch
contract validation       = PASS (207 schemas / 271 examples / 231 negative / 9 OpenAPI)
```

## Closure

P8-DEMO-S10 is complete. The installed domain consumers, immutable runtime
images, bounded startup credentials, signed-only service trust, restart
heartbeats, actual development database heads, cleanup, and changed-scope
quality gates are accepted for the Chairman Demo topology.
