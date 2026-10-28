# GB2-CA00-S08: Current Process Topology Closure

## Scope

S08 closes WS1 as the source-backed current Platform topology. It introduces
no database migration, business table, broker, scheduler, public business API,
or remote-provider dependency.

The closed topology is:

```text
deployment artifacts     = 9
installed processes      = 20
network processes        = 9
background processes     = 11
owner-local databases    = 8
promoted domain workers  = 3
```

The three promoted process bindings are canonical and package-native:

```text
nex-ae-agent-runtime-worker  -> nex-ae-runtime  / job_claiming
nex-wc-event-delivery-worker -> nex-wc-runtime  / event_delivering
nex-eos-outbox-publisher     -> nex-eos-runtime / outbox_publishing
```

None is classified as `lifecycle_only`.

## Runtime Reconciliation

`scripts/dev/run_platform.py` now selects the current 20-process manifest by
default. The frozen historical 13-process manifest remains available only by
the explicit compatibility option `--topology historical`.

The current protected profile now fails closed unless the direct WC-to-AE
endpoint and the WC/EOS-to-AE signed service-token edges are configured. The
complete protected profile contract is:

```text
test database environments = 8
service endpoints           = 10
signed trust edges          = 15
required environments       = 33
```

Each background process manifest also declares its owner-specific worker ID,
endpoint, token, timeout, poll, and capability configuration where applicable.
No process is given cross-service database access.

## Closure Contract

`nex_runtime.current_topology_closure` derives the closure from the current
artifact catalog, packaged entrypoints, process manifest, runtime profile, and
startup graph. It checks:

```text
9 artifacts / 20 bindings / 20 entrypoints
9 network endpoints / 11 background processes
package-native command source existence
absence of Demo runtime commands
direct promoted modules and real-work capabilities
complete promoted process environment contracts
20-process local and protected startup graphs
readiness-based protected dependency probes
20 process responsibility records / 8 DB owners
```

## Protected Topology Evidence

The opt-in S08 runner uses all eight actual `nex_*_test` PostgreSQL databases.
It applies and compares the complete migration inventory, verifies
`current_database()` and `current_user`, runs packaged `--check` for all eleven
background processes, imports all eight API packages, and composes the S05,
S06, and S07 protected work-loop evidence.

The promoted component evidence proves actual work, durable heartbeat,
restart/replay behavior, signed downstream trust where applicable, and zero
component residue. Remote embedding, reranking, and generation providers are
not required.

```text
evidence classification   = PROTECTED_TOPOLOGY
actual PostgreSQL DBs      = 8 / 8
protected checks           = 10 / 10
artifacts / processes      = 9 / 20
background checks          = 11 / 11
API package imports        = 8 / 8
promoted work loops        = 3 / 3
remaining component rows   = 0
result                     = PASS
```

The first run correctly failed because the S08 aggregate counted pre-cleanup
diagnostic counts as residue. The aggregation was corrected to count only
explicit `*_remaining` fields; no component cleanup behavior was weakened.

## Verification

```text
focused S08/topology regression = 45 passed
ruff / diff check               = PASS
actual PostgreSQL topology      = 10 / 10 PASS
Repository Full Gate            = 18,418 passed / 131 skipped
statement coverage              = 96.12% (threshold 96.00%)
branch coverage                 = 95.31% (threshold 94.00%)
contract validation             = 226 schemas / 290 examples / 244 negative / 10 OpenAPI
AE Web Node regression          = 403 passed / 0 failed
```

## Exit

```text
current 9/20 topology          = CLOSED
default current CLI topology  = PASS
historical compatibility      = PRESERVED EXPLICITLY
three real-work promotions    = PASS
protected PostgreSQL topology = PASS
zero residue                  = PASS
database migration            = NONE
remote provider required      = NO
next slice                    = GB2-CA00-S09
```
