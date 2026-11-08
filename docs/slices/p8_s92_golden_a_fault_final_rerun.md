# P8-S92: Golden A + Fault Final Re-run

## Status

Completed on 2026-10-24.

## Scope

P8-S92 re-ran the canonical Golden A protected journey and every required
P8.8 reliability variant against the same final-candidate source tree. It did
not add another business path, fault adapter, database table, migration, or
public contract.

The accepted candidate identity was:

```text
commit = 89f70d742d7ff40f01a990729499ad875ae88bf1
tree   = 8a375453925ebf228a64e61b6c79e05d8f87701d
```

P8-S93 remains responsible for recording the final as-built commit after the
P8-S92 evidence documentation itself is committed.

## Protected Environment

The accepted run used actual service-owned PostgreSQL test databases for AE,
WC, OA, and EOS. The provider preflight admitted all three live capabilities:

```text
embedding  = PASS / Qwen3-Embedding-4B
reranking  = PASS / Qwen3-Reranker-4B
generation = PASS / Qwen3.5-4B
```

The fault matrix used the digest-pinned RustFS image below with versioning and
SSE-S3 enabled:

```text
rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c
```

The admitted NSL identity remained unchanged:

```text
source revision = c0a8d4e125ee129c4556d896356237bb3973582d
source tree     = 057611c8c584afa5483f7f3e5990a19533ddea58
wheel sha256    = sha256:862958a5eab982a71bec5ee58b9e530867d6c25f65d8b770efb29ca78ce7f135
```

## Golden A Re-run

The S68 evidence composer re-ran the S67 protected journey instead of reusing
its historical business result. The current migrations were applied and
reported as:

```text
nex-ae-api = 2513_ae_voucher_attachment
nex-wc     = 1006_wc_approval_foundation
nex-oa     = 1376_oa_trace_projection_index
nex-eos    = 2513_eos_voucher_attachment_lineage
```

Acceptance result:

```text
actual PostgreSQL       = true
actual remote provider  = true
commit state            = COMMITTED
verification status     = VERIFIED
business mutations      = 1
cleanup residue         = 0
Golden A gate           = P8.6_GOLDEN_A_CLOSED
```

The evidence package also admitted the latest complete repository evidence:

```text
passed tests        = 17,238
failed tests        = 0
protected skips     = 111
statement coverage  = 96.7162%
branch coverage     = 96.1061%
```

This accepted package explicitly used the canonical S89 JUnit and coverage
artifacts under `reports/quality/`; it did not use the historical
`reports/coverage/` defaults.

## Fault Final Re-run

The accepted protected matrix explicitly selected S76 through S86 and enabled
every infrastructure guard. It covered:

```text
commit acknowledgement loss and UNKNOWN_COMMIT_STATE
COMMITTED / NOT_COMMITTED / still UNKNOWN reconciliation
COMMITTED plus deterministic verification failure
COMMITTED plus verification timeout/unknown
EOS outbox publication acknowledgement loss
approval event acknowledgement loss
worker crash after checkpoint
worker crash after WRITE_REQUESTED
current trust and authorization revocation
approval, payload, manifest, and tenant tamper rejection
complete reconciliation and post-WRITE verification recovery
```

Accepted result:

```text
selected tests = 13
passed         = 13
skipped        = 0
failed/errors  = 0
duration       = 53.867 seconds
```

The matching deterministic regression was also run with protected guards
disabled: `111 passed`, `13 expected protected skips`, and zero failure. The
separate protected execution above proves that every one of those 13 guarded
cases actually ran and passed.

One pre-acceptance infrastructure attempt was rejected because the ephemeral
RustFS SSE-S3 master key text did not decode to the required 32 bytes. No code
or contract change was needed. The container and anonymous volume were
discarded, a correctly encoded 32-byte key was injected, and all 13 tests were
re-run from the beginning for the accepted result above.

## Residue Closure

After the accepted run, a separate database audit enumerated every public
table with a `tenant_id` column in all four databases. Rows matching the P8-S92
fault tenant prefix were zero in AE, WC, OA, and EOS, including tenants from
the rejected setup attempt.

RustFS versioning correctly retained 25 immutable object versions and 25
delete markers after logical test deletion. The isolated test buckets were
therefore physically purged by exact version ID. A second inventory reported:

```text
object versions = 0
delete markers  = 0
affected buckets = nex-ae-p8-s76..s80 and nex-ae-p8-s83..s86
```

The ephemeral RustFS container and its anonymous data volume were then
discarded. This distinguishes normal versioned logical deletion from the
stronger zero-physical-residue requirement of the isolated acceptance run.

Local machine-readable evidence remains under the ignored `reports/quality/`
tree:

```text
p8-s92-provider-preflight.json
p8-s92-golden-a-evidence.json
p8-s92-fault-final.junit.xml
```

## Exit Decision

P8-S92 is closed. Golden A and every required P8.8 fault variant pass against
the same final-candidate tree with actual PostgreSQL, admitted NSL, live model
providers where required, and digest-pinned RustFS. Exactly-once mutation,
lineage stability, fail-closed authorization, reconciliation, verification,
tenant isolation, and zero final test residue remain intact. P8-S93 may create
the final P8 as-built baseline and P9 handoff.
