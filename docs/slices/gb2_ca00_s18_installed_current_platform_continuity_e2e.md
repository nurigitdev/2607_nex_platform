# GB2-CA00-S18 Installed Current-Platform Continuity E2E

## Scope

S18 promotes installed Golden A continuity evidence from the historical
P8-DEMO owner to the current Platform topology. It adds no database migration,
business API, runtime transition, or fixture-driven execution path.

## Current Installation Admission

The admission is derived from the canonical current sources:

```text
current runtime manifest       = 20 processes
current artifact catalog       = 9 artifacts
current packaged entrypoints   = 20 bindings
Compose deployment layers      = S143 + S146 + P8 promotion + P9 WA
journey continuity processes   = 9
additive WA processes          = 2
```

The historical overlay remains one additive deployment layer for WC/EOS, but
the S18 admission does not read or accept the P8-DEMO process manifest. Worker
commands are compared directly with current packaged entrypoints. The active
AE worker must use `nex_ae_api.agent_runtime_process --profile staging_live`,
contain `LOCAL_SKILL`, and contain no `demo_runtime` or `NEX_AE_DEMO_*` input.

## Golden Journey Ownership

`scripts/quality/golden_journey_runners.v1.json` now registers S18 as the sole
transition-enforced `GOLDEN_JOURNEY`. P8-DEMO S11 remains an
`INSTALLED_PLATFORM` compatibility runner. The existing transition audit still
forbids test-side scheduling, runtime job creation, approval mutation, result
ACK, work-result submission, and direct runtime-table mutation.

## Protected Boundary

The protected run requires actual PostgreSQL, Docker Compose, OpenBao, RustFS,
remote generation, signed service trust, Playwright, restart recovery, and
zero journey residue. Golden A is only the continuity probe. Product runtime
commands and authoritative OA/WC/EOS/PostgreSQL state remain the execution
source; no runtime business fixture is admitted.

## Verification

Source and regression verification completed as follows:

```text
S18/P8 transition focused regression       = 40 passed
WC/EOS/Compose surrounding regression       = 111 passed
EOS service regression                      = 750 passed / 22 skipped
Platform Slice Gate                         = 418 passed / 7 skipped
current installation statement / branch     = 100.00% / 100.00%
promoted WC/EOS worker statement / branch   = 100.00% / 100.00%
contract validation                         = 227 / 291 / 245 / 10
Golden Journey transition audit             = PASS (8 registered, 1 enforced)
```

Protected preparation also completed against all seven owner development
databases. A bounded pre-migration backup was written under
`/tmp/nex-platform-s18-postgres-backups`, and the canonical migration runner
confirmed all seven owners current after applying the missing OA migration.
The eight-image release set and the admitted AE NSL image passed non-root,
entrypoint, manifest, and package checks without a registry push.

The first actual PostgreSQL/Compose/provider/Playwright pass exposed a
PostgreSQL-specific lineage comparison: `agent_id` was returned as a UUID
while the protected AgentContext JSON held its canonical string form. The
product runtime now validates non-empty identifiers after canonical string
normalization, preserving fail-closed mismatch handling while accepting the
same identifier across SQLite and PostgreSQL driver representations.

The next protected pass correctly denied the requester at the EOS Project
read boundary. The requester was already an active Project member and had the
governed voucher WRITE scope, but the hash-locked tenant seed omitted the
separate `project:project:read` authority required to resolve its accessible
Project. The minimum user scope was added and both fixture hashes were
recomputed; AE-to-EOS service trust remains limited to `service:call`.

After the canonical VO00 reset/reseed, EOS Project resolution passed and the
next live boundary exposed an optional-field mismatch. OA omits
`org_scope_refs` when a user has no organization scope, while the product
runtime treated the field as mandatory. An omitted field now means an empty
organization scope; an explicitly malformed value is still rejected. The
separately resolved EOS Project scope remains authoritative.

The following live attempt reached NSL request binding and exposed a contract
drift hidden by the former fixture runtime. `SkillExecutionRequest` admits
only `USER`, `CONTEXT`, and `DEFAULT` provenance, while the product runtime
used an unregistered `AUTHORITATIVE` value. The governed payload is derived
from persisted context plus OA/EOS authority, so the runtime now emits the
existing canonical `CONTEXT` provenance without expanding the shared schema.

The broad WC package diagnostic completed with `548 passed / 21 skipped`, but
its historical package-wide coverage was `90.64% / 90.00%`; this does not meet
the Slice threshold. The changed `event_delivery_process` is independently
measured at `100.00% / 100.00%`. No threshold or source exclusion was changed.

The protected runner is the authoritative live evidence owner. It records a
PASS only when rebuilt current images complete actual PostgreSQL, Compose,
OpenBao, RustFS, remote generation, authenticated Playwright, restart/replay,
stable-queue, and zero-residue checks in one execution.
