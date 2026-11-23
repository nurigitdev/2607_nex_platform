# W80-CA00D: NeX-MO Capability-Scoped Readiness and Healthcheck Boundary

**Status:** COMPLETE

## Scope

- keep NeX-MO `/ready` shallow and free of remote-provider inference;
- add optional capability selection to the protected provider health API;
- preserve no-query all-provider compatibility;
- isolate readiness caches by requested capability set;
- bind the AE generation client to generation-only readiness;
- reconcile the historical S113 closure through explicit supersession.

No database migration, provider revision change, or business API change is in
scope.

## Verification

- focused MO/AE readiness tests: `141 passed`;
- contract validation: `274` schemas, `320` positive examples, `260` negative
  examples, and `10` OpenAPI documents passed;
- NeX-MO Slice Gate: `1,331 passed`, `6 skipped`, statement `99.80%`, branch
  `99.39%`;
- NeX-AE Slice Gate: `6,926 passed`, `53 skipped`, statement `96.45%`, branch
  `94.68%`;
- Repository Full Gate: `23,910 passed`, `193 skipped`, statement `96.32%`,
  branch `95.26%`, exit code `0`;
- historical S113 closure passed with the explicit W80-CA00D supersession;
- protected live provider probes were not required because this Slice changes
  capability selection and healthcheck composition, not provider behavior or
  model revisions.

## Post-Closure Installed Live Confirmation

The exact-head `28df627d` release set was rebuilt and the protected two-request
M1 journey was rerun against actual eight-service PostgreSQL, OpenBao, RustFS,
Qwen3.5-9B, and authenticated Playwright. The journey, restart recovery, 17
screen captures, and eight-schema zero-residue cleanup all passed.

The admitted NeX-MO traffic contained 12 generation requests, 12
`capability=generation` readiness requests, and zero embedding or reranking
requests. Compared with the immediately preceding accepted diagnostic session:

- `/ready` checks changed from `database + provider_routes` to `database`;
- `/ready` mean latency changed from `70.5 ms` to `20.7 ms`;
- `/ready` p95 changed from `524.8 ms` to `24.2 ms`;
- cumulative `/ready` time changed from `12.47 s` to `3.53 s`;
- the complete diagnostic span changed from `628.46 s` to `604.76 s`.

The final span is observational rather than a controlled provider benchmark.
Generation latency also varied between runs, so only the shallow `/ready`
reduction and absence of unrelated provider calls are attributed directly to
W80-CA00D.
