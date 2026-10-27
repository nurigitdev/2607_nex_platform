# P9-S06: WA Intake Contracts and Deterministic Job Identity

## Scope

P9-S06 freezes the reference-only source inspection request used by NeX-WA.
It does not expose an HTTP route, persist a Job, fetch an authoritative source,
or admit evidence as true. Those behaviors begin in P9-S07 and P9-S08.

Canonical contracts:

```text
wa_evidence_intake_request.v1
wa_evidence_intake_admission.v1
wa_error.v1
```

## Source Boundary

External intake admits exactly:

```text
AE_AGENT_RESULT
AE_ARTIFACT
```

`WC_WORK_RESULT` remains a valid internal supporting source type and is not an
independent Foundation ingress. Unknown fields are rejected, which excludes raw
prompts, document bodies, artifact bytes, credentials, tokens, payroll values,
and other unbounded business payloads from the JobQueue boundary.

## Deterministic Identity

The request is normalized before identity derivation. `job_id` is UUIDv5 under
the `nex-wa-evidence-ingest-v1` namespace and `idempotency_key` uses the shared
`nex_runtime.semantic_hashes.semantic_sha256_hash_ref()` helper.

Both values bind only:

```text
tenant_id
source_type
source_ref
source_revision_ref
```

`source_hash`, notification time, request ID, and trace ID do not affect Job
identity. Reusing the source identity with a different `source_hash` returns
`WA_SOURCE_IDEMPOTENCY_CONFLICT`; changed delivery metadata alone is a valid
replay.

## Contract Evidence

```text
schemas added            = 3
positive examples added  = 3
negative fixtures added  = 3
contract validation      = PASS
catalog totals           = 210 schemas / 274 examples / 234 negatives
```

Negative fixtures prove raw prompt rejection, external `WC_WORK_RESULT`
rejection, and malformed source hash rejection.

## Quality Evidence

```text
focused P9-S06 tests         = 34 passed
intake module statement      = 100.00%
intake module branch         = 100.00%
P9-S06 Slice Gate            = 111 passed, 4 skipped
Slice statement coverage     = 99.62%
Slice branch coverage        = 97.86%
contract validation          = PASS
```

The four skipped tests are protected PostgreSQL smokes from P9-S02 through
P9-S05; P9-S06 adds no persistence behavior and therefore does not claim a new
database smoke.

## Exit

```text
reference-only request boundary       = PASS
deterministic UUIDv5 Job identity      = PASS
shared canonical SHA-256 identity key = PASS
same-hash replay                       = PASS
different-hash conflict                = PASS
privacy and bounded-payload rejection  = PASS
next Slice                             = P9-S07
```
