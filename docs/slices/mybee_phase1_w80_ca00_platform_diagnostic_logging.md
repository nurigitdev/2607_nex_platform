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
live journey. The next product boundary remains `W80-CA01`.
