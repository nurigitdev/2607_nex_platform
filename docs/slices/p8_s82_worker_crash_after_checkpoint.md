# P8-S82: Worker Crash After Checkpoint

## Status

Completed on 2026-10-24. P8-S83 is next.

## Boundary

P8-S82 injects one worker failure after the admitted NSL checkpoint is durable
but before AE/WC approval publication begins:

```text
NSL controlled prefix
-> durable checkpoint and canonical ApprovalRequest available
-> checkpoint/request lineage validated
-> first worker publication attempt crashes
-> restarted attempt reloads the same checkpoint and request
-> one AE protected ApprovalRequest
-> one AE NSL approval wait
-> one WC ApprovalWorkItem
-> one approval event and RESUME_EXECUTION job
-> one exclusive NSL checkpoint consume
```

The recovery path does not infer or recreate NSL semantics. It reuses the
existing `P8NSLApprovalPort`, protected request store, wait repository, WC
idempotent `create_or_get`, approval event inbox, runtime job deduplication,
and NSL resume claim/consume behavior.

## Implementation

`WorkerCrashAfterCheckpointFaultPort` is a protected test adapter. Before
injecting the crash it requires and records the exact:

```text
NSLExecutionId
BusinessOperationId
checkpoint_version
checkpoint integrity hash
Skill semantic hash
ApprovalRequestId
ApprovalRequest semantic hash
PayloadHash
protected payload reference
```

On the restart attempt it reloads the durable checkpoint and rejects any
checkpoint or ApprovalRequest drift before invoking the downstream approval
port. Only the exact restart is allowed to publish.

The P8-S53 actual approval/resume harness gained an optional publication
factory. Its default path remains unchanged. S82 activates the factory and
records request, wait, and WorkItem counts before continuing through the
existing decision, event, resume worker, and cleanup journey.

No production API, event schema, table, or migration changed.

## Attachment And Manifest Invariant

The attachment manifest remains inside the governed protected payload. S82
pins its semantic identity through the unchanged PayloadHash and protected
payload reference across the crash and restart. The restarted worker does not
upload, rewrite, or copy a RustFS object.

Actual attachment storage immutability was established by P8.7A and the
attachment-bearing P8-S76 through P8-S80 evidence. P8-S86 still requires one
complete attachment-bearing reliability journey.

## Actual PostgreSQL Evidence

The protected S82 gate used the admitted NSL v0.2 wheel and actual:

```text
nex_ae_user @ nex_ae_test
nex_wc_user @ nex_wc_test
```

APPROVE, REJECT, and expiry each produced:

```text
publication attempts             = 2
injected worker crashes          = 1
restart attempts                 = 1
downstream publications          = 1
protected ApprovalRequest rows   = 1
NSL approval wait rows           = 1
WC ApprovalWorkItem rows         = 1
RESUME_EXECUTION rows            = 1
checkpoint consumed              = true
runtime job final state          = DONE
EOS mutation count               = 0
test database residue            = 0
```

Protected result:

```text
1 passed
0 skipped
```

Remote generation, embedding, and reranking providers were not required.
RustFS was not required because this Slice verifies immutable protected
references and performs no object mutation.

## Regression And Quality Gate

P8 focused regression:

```text
1,640 passed
56 protected opt-in skipped
```

NeX-AE Slice Gate:

```text
pytest                       = 5,362 passed / 44 protected opt-in skipped
statement coverage           = 98.33% / required 95.00%
branch coverage              = 96.31% / required 94.00%
reliability fault scope      = 100.00% statement / 100.00% branch
contract validation          = 191 schemas / 253 positive / 221 negative / 9 OpenAPI
gate commands                = 5 / 5
gate exit                    = 0
```

The shared reliability-fault scope explicitly includes the EOS-owned P8-S80
test so the AE and EOS branches are measured together. The protected S82
scenario has separate zero-skip evidence above.

## Exit Decision

P8-S82 is closed. A failure after checkpoint durability cannot create a
second approval semantic unit, change the protected payload/manifest identity,
or consume the checkpoint twice. P8-S83 may now inject a worker crash after
`WRITE_REQUESTED` and require idempotency/reconciliation rather than assuming
`NOT_COMMITTED`.
