# NeX MyBee W80-CA00D NeX-MO Capability-Scoped Readiness and Healthcheck Boundary v1.0

**Status:** CLOSED

**Predecessor:** W80-CA00C

**Database migration:** None

## 1. Purpose

The installed M1 journey uses NeX-MO generation, but the Docker healthcheck and
AE semantic-stage preflight caused embedding, reranking, and generation probes
to appear together. The business path did not call embedding or reranking.
Those calls came from an all-provider readiness boundary that was broader than
the capability actually required by the caller.

W80-CA00D separates service liveness/readiness from active provider admission
and makes provider checks capability-scoped without changing provider API
payloads, model aliases, or business behavior.

## 2. Source-Backed Finding

The M1 debug evidence showed generation requests and provider-route-health
requests, but no NeX-MO embedding or rerank business request. Source inspection
confirmed two independent causes of the extra provider traffic:

1. Docker called `GET /ready` repeatedly and NeX-MO composed all three active
   provider probes into that shallow service endpoint.
2. AE generation readiness called the aggregate provider-route-health endpoint
   before semantic generation stages.

The probes were therefore real remote calls but were readiness traffic, not
hidden RAG execution.

## 3. Boundary Decision

1. `GET /ready` proves the NeX-MO process and database dependency only. It must
   not contact a remote model provider.
2. `GET /api/v1/provider-route-health` remains the protected active provider
   admission endpoint.
3. The optional `capability` query accepts `embedding`, `reranking`, or
   `generation` and probes only that capability.
4. Omitting `capability` preserves the existing aggregate three-provider
   operations contract.
5. AE semantic generation requests `capability=generation`; it cannot trigger
   embedding or reranking readiness.
6. Readiness snapshots and configuration identities are cached independently
   by the exact capability tuple.
7. Unknown capability values fail before provider access and cannot fall back
   to an aggregate probe.
8. Provider failures remain fail-closed for the requested capability.

## 4. Compatibility and Supersession

S113 introduced provider-aware route health and composed all providers into
`GET /ready`. W80-CA00D preserves the protected S113 route-health API and the
no-query aggregate projection, but supersedes the shallow service-readiness
composition because it coupled container health to every remote provider.

```text
S113 ALL-PROVIDER /ready POLICY = SUPERSEDED
PROTECTED AGGREGATE ROUTE HEALTH = PRESERVED
CAPABILITY-SCOPED ROUTE HEALTH   = ADDED
```

Operations that need a complete provider view continue to omit the query.
Capability consumers must request only the capability they will execute.

## 5. Security and Privacy

- the route remains protected by the existing NeX-MO service bearer boundary;
- provider endpoints, API keys, model paths, and private response payloads are
  never projected;
- no public unauthenticated provider probe is added;
- no provider credential moves into AE;
- no raw prompt, plan, or generation payload is added to readiness evidence.

## 6. Acceptance

1. generation-scoped readiness executes only the generation probe;
2. embedding, reranking, and generation caches are independent;
3. no-query route health still returns all required capabilities;
4. malformed capability input is rejected without remote access;
5. AE generation client uses the generation-scoped route;
6. NeX-MO `GET /ready` remains database fail-closed and provider-network-free;
7. JSON Schema and OpenAPI admit one-to-three unique required capabilities;
8. historical S113 closure recognizes this explicit supersession;
9. focused MO/AE tests, service Slice Gates, contract validation, and the
   Repository Full Gate pass before closure.

## 7. Decision

```text
SHALLOW /ready REMOTE PROBES       = FORBIDDEN
ACTIVE PROVIDER ADMISSION          = PROTECTED ROUTE HEALTH
CALLER CAPABILITY SELECTION        = REQUIRED WHEN KNOWN
NO-QUERY AGGREGATE COMPATIBILITY   = PRESERVED
CAPABILITY CACHE ISOLATION         = REQUIRED
DATABASE MIGRATION                 = NONE
MODEL OR PROVIDER REVISION CHANGE  = NONE
```

## 8. Verification Evidence

- focused MO/AE readiness tests: `141 passed`;
- contract validation: `274` schemas, `320` positive examples, `260` negative
  examples, and `10` OpenAPI documents passed;
- NeX-MO Slice Gate: `1,331 passed`, `6 skipped`, statement `99.80%`, branch
  `99.39%`;
- NeX-AE Slice Gate: `6,926 passed`, `53 skipped`, statement `96.45%`, branch
  `94.68%`;
- Repository Full Gate: `23,910 passed`, `193 skipped`, statement `96.32%`,
  branch `95.26%`, exit code `0`.

The protected live-provider matrix was not required for closure. No provider
request contract, model binding, or revision changed; the Full Gate instead
proved compatibility of the capability selector, shallow readiness boundary,
aggregate operations route, and historical closure chain.

## 9. Post-Closure Installed Live Confirmation

An exact-head installed replay was subsequently executed to measure the
operational effect rather than to reopen source admission:

- source revision: `28df627d40f783028d11f9eef547753346b1edab`;
- release set: `9/9` exact-head OCI images plus exact-head AE product runtime;
- provider: Qwen3.5-9B revision
  `hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a` on deployment
  `dgx-qwen3-5-9b-9111`;
- infrastructure: actual eight-service PostgreSQL, OpenBao, RustFS, Docker
  Compose, and authenticated Playwright;
- result: two Agent executions, six approval decisions, two immutable
  journals, two allocation batches, four allocation lines, four P&L
  projections, and two acknowledged result deliveries;
- restart recovery: result hash and business references remained stable;
- evidence: 44 diagnostic files, raw prompt, AgentPlan, ExecutablePlan, 15
  journey captures, two recovery captures, and no admitted secret value;
- cleanup: eight isolated schemas dropped with `zero_residue=true`.

The first attempt failed before provider contact when OpenBao `/sys/init`
returned a transient transport error. Its eight isolated schemas were removed
with zero residue. A clean replay passed without changing source or runtime
configuration.

### 9.1 NeX-MO Traffic Proof

The previous accepted diagnostic session exposed aggregate route health and
remote provider composition through shallow readiness:

```text
provider route capabilities = embedding, reranking, generation
/ready checks               = database, provider_routes
```

The W80-CA00D replay proved:

```text
generation requests                  = 12
generation-scoped readiness requests = 12
embedding requests                   = 0
reranking requests                   = 0
/ready checks                        = database
```

### 9.2 Observed Latency

| Signal | Before W80-CA00D | After W80-CA00D |
|---|---:|---:|
| `/ready` mean | `70.5 ms` | `20.7 ms` |
| `/ready` p95 | `524.8 ms` | `24.2 ms` |
| cumulative `/ready` time | `12.47 s` | `3.53 s` |
| full diagnostic span | `628.46 s` | `604.76 s` |

The two-request browser journey took `557.08 s` from the ready requester flow
through the second rendered result. Individual request-to-admission intervals
were `130.32 s` and `133.67 s`; full request-to-result intervals were
`276.02 s` and `281.06 s`.

Only the shallow readiness reduction and provider-call isolation are causal
W80-CA00D evidence. Qwen3.5-9B generation latency changed between sessions and
the end-to-end difference must therefore remain an observational measurement,
not a controlled performance claim.
