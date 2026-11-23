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
