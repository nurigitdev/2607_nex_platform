# W80-CA00: Platform Diagnostic Logging and Live-Journey Evidence Boundary

## Scope

W80-CA00 adds a restricted evidence plane for source-backed live debugging
without changing business schemas or public APIs. It deliberately includes raw
prompt, internal candidates, AgentPlan, ExecutablePlan, HTTP payloads, and step
input/output in explicitly admitted `LIVE_JOURNEY` sessions. Credentials remain
redacted in every mode.

The controlling design record is:

```text
docs/transition/MyBee_Phase1/NeX_MyBee_W80_CA00_Platform_Diagnostic_Logging_and_Live_Journey_Evidence_Boundary_v1.0.md
```

## Implementation

- Added the shared `DiagnosticEvidencePolicy` and hash-chain JSONL recorder.
- Added shared FastAPI HTTP exchange evidence with JSON/text capture and opaque
  multipart/binary digest projection.
- Instrumented AE semantic admission through WorkIntent, candidate, AgentPlan,
  validation, and ExecutablePlan.
- Instrumented the installed AE step handler with RuntimeJob, executable step,
  step-result, and failure evidence.
- Added canonical Docker `local` log rotation and a private diagnostic volume.
- Added pre-teardown live-runner collection for every installed service/process
  log, evidence session, source identity, and manifest digest.
- Added non-root OCI diagnostic directory ownership.

## Validation

Focused validation covers policy admission, secret redaction, metadata omission,
raw Agent data, hash chaining, manifest/file permissions, HTTP JSON and
multipart boundaries, semantic compilation, runtime step execution, Compose
admission, installed-acceptance finalization, and live evidence collection.

```text
focused regression             = 121 passed
AE Slice Gate                  = PASS
AE regression                  = 6,917 passed / 53 protected skips
AE statement / branch          = 96.45% / 94.67%
AE coverage ownership          = PASS (197 modules, 0 conflicts)
contract validation            = PASS (274 schemas / 320 examples /
                                 260 negative examples / 10 OpenAPI)
golden journey audit           = PASS
demo/product dependency audit  = PASS
nex-runtime regression         = 2,151 passed / 1 protected skip
diagnostic_evidence.py          = statement 100% / branch 100%
diagnostic_http.py              = statement 100% / branch 100%
```

The broad historical `nex-runtime` profile is not an admitted Gate result. It
selects shared source modules that its service test inventory does not own and
therefore reports statement `87.06%` and branch `84.15%` against the repository
thresholds of `95%` and `94%`. Its complete selected regression passed and both
new diagnostic modules have full statement and branch coverage. Reconciliation
of that pre-existing source/test ownership scope remains separate from this
boundary.

The Slice does not require a remote provider and does not claim a new protected
live journey for source admission. A post-implementation protected journey was
executed separately as recorded below. The next product boundary remains
`W80-CA01`.

## Protected Live Evidence

An exact-head installed journey was executed on 2026-11-22 from commit
`95fd485717ed673e7b574a7da7b184c5dc90c7fa`. The canonical nine-image set and
the AE product runtime image were rebuilt from that revision before execution.
The journey used the actual eight development PostgreSQL databases, OpenBao,
RustFS, Playwright, and the canonical Qwen3.5-9B generation provider revision
`hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a`.

```text
protected installed journey     = PASS
actual PostgreSQL               = PASS
actual remote generation        = PASS
authenticated Playwright        = PASS
post-restart recovery           = PASS
isolated DB cleanup             = PASS (8/8, zero residue)
diagnostic session              = mybee-w70-m1-20261122T072820Z-79496748
manifest files                  = 25
manifest SHA-256                = 7f5012c04ea6608dc02e50f2681f3644
                                  231340a815881a1bbf8851803bd8949b
diagnostic events               = 5,878
HTTP exchanges                  = 5,836
semantic candidates             = 12
compiled executable plans       = 2
runtime step start/completion   = 10 / 10
raw prompt present              = PASS
AgentPlan present               = PASS
ExecutablePlan present          = PASS
secret redaction paths          = 10,166 across 4,718 events
known API key/password exposure = 0
Bearer/Authorization exposure   = 0
container residue               = 0
```

The first operator attempt used a plain `postgresql://` SQLAlchemy URL and was
rejected before Compose/provider execution because the environment does not
install `psycopg2`. Its eight isolated schemas were removed with zero residue.
The admitted retry used the canonical `postgresql+psycopg://` driver form and
passed. This was an execution-configuration correction, not a product-code
change.

The raw evidence set remains under the ignored `reports/` boundary with mode
`0700` on the session directory and `0600` on evidence files. Raw prompt, plan,
and API content must not be committed to Git.
