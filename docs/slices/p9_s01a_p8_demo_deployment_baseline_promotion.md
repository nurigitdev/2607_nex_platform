# P9-S01A: P8-DEMO Deployment Baseline Promotion and WA Ninth-Image Reconciliation

## Problem

P9-S01 registered NeX-WA by expanding the historical S142 default deployment
catalog from six images to nine. P8-DEMO already owned an additive eight-image
release set: the S142 six-image baseline plus NeX-WC and NeX-EOS. Expanding the
historical default caused the P8-DEMO builder to add WC/EOS twice and left WA
without a P8-DEMO process binding.

The failure was a baseline-layering defect, not missing WC/EOS implementation.
The P8-DEMO merge commit and its installed runtime, Compose, OCI, and protected
journey code remain authoritative.

## Decision

Deployment baselines are explicit and additive:

```text
S142 historical default = 6 images / 13 processes
P8-DEMO promoted set     = 8 images (historical + WC + EOS)
P9 current set           = 9 images (P8-DEMO + WA)
```

Existing `default` APIs retain their frozen S142 semantics. New `current` APIs
own the P9 topology, runtime profile, environment composition, packaged
entrypoints, and OCI definitions. This preserves historical evidence while
making WC, EOS, and WA first-class in the current deployment set.

NeX-WA adds only:

```text
artifact  = nex-wa-runtime
target    = wa-runtime
API       = nex-wa-api
worker    = nex-wa-evidence-consumer
port      = 8108
```

The WC and EOS images, entrypoints, and ports are reused from P8-DEMO. They are
not reimplemented by P9.

## Verification

The focused baseline reconciliation covers:

- frozen six-image deployment and production configuration regressions;
- exact P8-DEMO eight-image OCI/process/Compose regressions;
- exact P9 nine-image and seventeen-process coverage;
- current packaged API and background entrypoints;
- WA OCI target and non-root Containerfile admission;
- protected current-profile DB, endpoint, trust, and immutable image inventory;
- fail-closed admission when the WA test database URL is absent.

Verification evidence:

```text
focused EOS/WA/baseline regression = 41 passed
P9-S01A Slice Gate                 = 460 passed, 6 skipped
Slice statement coverage           = 99.75%
Slice branch coverage              = 99.65%
Repository Checkpoint Gate         = 17,212 passed, 121 skipped
Checkpoint statement coverage      = 98.25%
Checkpoint branch coverage         = 96.72%
contract validation                = PASS (207 schemas, 271 examples,
                                      231 negative examples, 9 OpenAPI specs)
```

The first Checkpoint run exposed one P8 test that assumed NeX-EOS was the last
developer-service entry. That assertion now verifies EOS membership, while the
P9 test owns the new WA tail-position expectation. The successful rerun above
confirms the distinction.

## Exit

```text
historical baseline preserved       = YES
P8-DEMO WC/EOS reused               = YES
P9 WA ninth image admitted          = YES
duplicate WC/EOS artifacts          = NO
unbound WA artifact                 = NO
new domain behavior                 = NO
database migration                  = NO
```
