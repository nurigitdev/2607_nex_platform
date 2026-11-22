# W40-CA02-S02 Canonical Installed Configuration, Trust, and Process Wiring

## Status

`CLOSED` on 2026-11-13.

This Slice promotes the MyBee product library into the existing canonical AE
runtime artifact and makes protected AE worker startup fail closed when the
exact package identity or VoucherCandidate consumer surface is unavailable.
It reuses the existing signed AE-to-EOS and EOS-to-OA trust topology and adds
no service, process, database, API, or business mutation.

## Installed Ownership Wiring

- `nex-ae-runtime` is the only OCI artifact whose owner-scoped source roots
  include `domains/mybee/mybee_ax`.
- The AE stage of `python-service.Containerfile` copies the package to
  `/app/domains/mybee/mybee_ax` and exposes only `/app/domains/mybee` through
  `PYTHONPATH`.
- OA, EOS, WC, and every other runtime artifact exclude the MyBee source root.
- The derived canonical AE product image requires both the admitted NSL bundle
  and MyBee package admission before the non-root image can complete.
- No MyBee runtime entrypoint, worker, JobQueue, database, or Compose service
  was introduced.

## Fail-Closed Package Admission

Added `nex_ae_api.mybee_product_admission` with the following exact checks:

1. importable package identity `mybee_ax`;
2. `DOMAIN_ID == "mybee"`;
3. `PACKAGE_VERSION == "0.1.0"`;
4. exact canonical owner set;
5. public `HttpVoucherCandidateProviderTransport`; and
6. public `NexVoucherCandidateClient`.

The projection contains no payload or secret. Import errors are reduced to a
typed reason code and do not expose filesystem or provider details.

`staging_live` and `production` Agent Runtime processes require this admission
even when an executor profile is injected. `test` retains `NOT_REQUIRED` so
deterministic component tests do not become product-package tests. Readiness
now exposes `mybee_product_package_admitted` and the redacted admission
projection.

## Trust And Process Decision

No new credential was needed. The installed path reuses the existing canonical
trust grants:

```text
AE  -> EOS: NEX_AE_TO_EOS_SERVICE_TOKEN / audience nex-eos / service:call
EOS -> OA : NEX_EOS_TO_OA_SERVICE_TOKEN / audience nex-oa /
            service:call, authorization:read,
            identity:employee:resolve, project-entitlement:write
```

Both credentials remain OpenBao secret references in canonical Compose and are
materialized only by `nex_runtime.production_container_bootstrap`. Browser
code and MyBee source never receive EOS-to-OA credentials. The existing
processes remain authoritative:

- `nex_ae_api.agent_runtime_process --profile staging_live`;
- `nex_eos.outbox_publisher_process --profile staging_live`.

## Capability Boundary

The remaining product capability and activator gaps are deliberately not
closed with placeholder metadata. `ProductCapabilityRegistry` admits only a
real `LOCAL_SKILL` artifact with exact version, semantic hash, runtime contract,
trust policy, and bundle identity. The current MyBee VoucherCandidate surface
is an HTTP consumer, not an admitted NSL Skill.

Therefore S02 preserves the existing Golden A registration without fabricating
a MyBee Skill. `W40-CA02-S03` must introduce the real consumer activation
binding and capability together, or explicitly prove a non-NSL activation
contract. The executable ownership audit now reports:

```text
status=PASS
integration_readiness=NOT_READY
integration_gaps=2
next_slice=W40-CA02-S03
```

The two remaining gaps are:

- `MYBEE_PRODUCT_CAPABILITY_NOT_ADMITTED`;
- `MYBEE_PRODUCT_ACTIVATOR_NOT_ADMITTED`.

## Actual OCI Evidence

The owner-scoped AE base and derived product image were built locally without a
registry push:

```text
image: nex-platform-canonical/nex-ae-runtime:w40-ca02-s02
status: PASS
runtime user: 65532:65532
source revision: 3a81d4614da2b7ee988203a1d8088133d967b88f
image/manifest digest: sha256:fe4d2197112aec2196cdc63f2b2f01d1c7f5750a8f09df60a9a94edd7570b45a
source context digest: sha256:a877856066c2e0c942fe6743bc794cdefca4982fead11e2ad37870c3e038a308
build inputs digest: sha256:793795f3389debaa35736d2e32019dc26faaaa5fc6819cb7502a64e04cc4c377
NSL bundle admission: PASS
MyBee package admission: PASS
registry push: false
```

Local machine-readable evidence:

- `reports/deployment/w40-ca02-s02-ae-runtime-image.json`

The report is intentionally ignored by Git.

## Validation

Focused configuration, package, OCI, and Agent Runtime regression:

```text
57 passed
```

Existing product runtime, capability registry, canonical trust, Compose, and
orchestration regression:

```text
151 passed
```

New admission module coverage:

```text
statement coverage: 100%
branch coverage: 100%
```

NeX-AE Slice Gate:

```text
status: PASS (5/5 commands)
tests: 5,927 passed, 46 protected/optional skips
statement coverage: 97.00% (threshold 95.00%)
branch coverage: 95.20% (threshold 94.00%)
contract validation: PASS (245 schemas, 303 examples, 254 negative, 10 OpenAPI)
Golden Journey transition audit: PASS
Demo/product dependency audit: PASS
```

Coverage evidence:

- `reports/quality/mybee-w40-ca02-s02-ae-slice-gate.coverage.json`

No PostgreSQL smoke was required because this Slice introduced no migration or
database access. No embedding, reranker, or generation provider was used.

## S03 Entry Decision

`W40-CA02-S03` may proceed. It must connect the installed MyBee HTTP consumer
to a real AE-owned activation boundary, use the existing signed AE-to-EOS
credential, and prove EOS-to-OA entitlement convergence through the installed
outbox publisher. A fake transport, placeholder capability, direct EOS import,
or direct database mutation remains prohibited.
