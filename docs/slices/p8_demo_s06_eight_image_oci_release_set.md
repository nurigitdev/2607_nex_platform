# P8-DEMO-S06: Eight-Image OCI Release Set

## Outcome

The P8 Demo release has an additive eight-image catalog without changing the
historical six-image S142 catalog or its evidence:

```text
nex-oa-runtime
nex-ag-runtime
nex-ae-runtime
nex-cx-runtime
nex-mo-runtime
nex-wc-runtime
nex-eos-runtime
nex-ae-web
```

WC and EOS now have digest-pinned, non-root `wc-runtime` and `eos-runtime`
targets in the shared Python Containerfile. Worker and publisher containers
reuse the immutable image owned by their service; no extra image identity is
introduced.

## Protected Build

`scripts/deployment/build_p8_demo_images.py` creates owner-scoped build
contexts, builds all eight images, inspects image/config/manifest digests and
labels, verifies non-root users and packaged commands, and admits only an exact
release set. It performs no registry push and no production contact.

The runner requires both:

```text
--execute
NEX_P8_DEMO_OCI_IMAGE_BUILD=1
```

Untracked files outside every declared build context are reported but cannot
contaminate the source identity. Tracked changes or untracked files inside a
Containerfile/build context fail the build.

## Background Package Checks

The AE runtime worker, WC event-delivery worker, and EOS outbox publisher are
executed inside their images with `--check`, no network, a read-only root, and
an explicit `NEX_DEMO_RUNTIME_CHECK_MODE=PACKAGE` boundary. The result must
state:

```text
package_ready = true
runtime_ready = false
database.status = NOT_REQUESTED
secret_included = false
```

This offline package check cannot be mistaken for S05's actual PostgreSQL
readiness evidence or S10's domain-work activation.

## Verification

- exact eight-artifact and eleven-process ownership validation;
- WC/EOS target and owner-scoped context validation;
- immutable base/builder image and dependency-lock validation;
- deterministic fake-Docker orchestration regression;
- actual Docker eight-image build and three container package checks;
- unique image ID and manifest/config digest validation;
- complete release-set provenance with registry push disabled;
- focused Slice Gate and historical S142 deployment regression.

Protected evidence is written to the ignored
`reports/deployment/p8-demo-oci-image-build.json` and its redacted build logs.
P8-DEMO-S07 consumes only the admitted complete release set.
