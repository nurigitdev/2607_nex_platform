# CP-M1-E2E-FX-01B.6B.5B.4 Compose, OCI, And Topology Promotion

## Scope

This Slice promotes the installed WC assignment dispatcher from the `.5B.3`
process boundary into the canonical Platform deployment. It does not add a
tenth image, a business fixture, a migration, or a remote-provider dependency.

## Implemented Boundary

- registered `nex-wc-assignment-dispatch-worker` as the twenty-first current
  Platform process and the twelfth background process;
- bound the process to the existing `nex-wc-runtime` artifact with the
  `assignment-dispatch-worker` entrypoint and `job_claiming` capability;
- bound the package-native command to
  `python -m nex_wc.assignment_dispatch_process --profile <profile>`;
- added the WC database, AE Agent Registry, OA authorization, worker identity,
  timeout, poll, and scan-limit environment inventory;
- added `NEX_WC_OA_BASE_URL` and `NEX_WC_TO_OA_SERVICE_TOKEN` to the protected
  current-profile fail-closed contract;
- installed the canonical Compose service with the existing WC OpenBao secret
  boundary, non-root production bootstrap, read-only filesystem, dropped
  capabilities, and no published port;
- added a PID 1 liveness healthcheck; application readiness remains the
  process-start DB/migration/dependency check plus durable heartbeat contract;
- fixed startup ordering on healthy OpenBao, WC API, AE API, and OA API;
- extended canonical topology, installation, Compose-render, OCI package-check,
  and historical-baseline reconciliation from twenty to twenty-one processes;
- added a dispatcher-specific rollback guard that rejects command, dependency,
  security, and demo/fixture/M1 scenario residue drift.

## Verification

| Evidence | Result |
|---|---|
| focused topology, deployment, OCI, and historical regression | `53 passed, 1 skipped` |
| dispatcher Compose/OCI/topology tests plus deployment regression | `38 passed` |
| current trust, process-manifest, artifact, and entrypoint regression | `83 passed` |
| WC Slice Gate | `733 passed, 25 skipped`; statement `98.18%`, branch `96.03%` |
| shared-runtime functional regression | `2103 passed, 1 skipped` |
| changed installation admission focused coverage | statement `100.00%`, branch `100.00%` |
| canonical Compose source admission | `SOURCE_ADMITTED` |
| actual Docker Compose config render | `PASS`; 18 services, 9 images, 21 processes |
| package-only dispatcher check | `PASS`; package ready, runtime/database not contacted |
| non-root OCI contract | `USER 65532:65532`; existing `wc-runtime` target |
| canonical image build | all 9 images built from commit `59429f6a` |
| complete release-set package matrix | `BLOCKED` at the pre-existing AE worker: NSL wheel absent from the generic AE image |
| remote provider | not required and not contacted |
| actual WC/OA/AE PostgreSQL handoff | deferred to `.5B.5` by contract |

The protected PostgreSQL topology test remains opt-in and was skipped in the
focused regression. That is intentional for this deployment-only Slice;
`.5B.5` owns the actual WC/OA/AE database, concurrency, restart, and handoff
delivery Gate.

The broad `nex-runtime` Slice profile completed all 2,103 functional tests but
its repository-wide shared-runtime coverage aggregation remains below 95/94
because it includes historical and inactive modules with zero or intentionally
partial coverage. The threshold was not lowered. The changed installation
admission module is measured separately at 100/100, while the other changed
runtime topology modules remain between 98% and 100% in the broad report.

The official canonical build produced all nine immutable images. The new WC
image then passed the isolated command below inside the container:

```text
python -m nex_wc.assignment_dispatch_process --profile local_mock --check
```

The release-set runner stopped before recording a complete set because the
existing AE worker imports `nsl.adapters.ed25519`, while the generic
`nex-ae-runtime` image does not package the admitted NSL wheel. The failure is
`ModuleNotFoundError: No module named 'nsl'`. This is outside the assignment
dispatcher implementation, but it is an installed-platform blocker and must
not be hidden by treating the owner-scoped WC check as a full release PASS.

## Decision

`CP-M1-E2E-FX-01B.6B.5B.4` closes the canonical topology and owner-scoped WC
OCI entrypoint/check without lowering an owned coverage boundary. Progress to
`.5B.5` is paused. The recommended next boundary is a short corrective Slice,
`CP-M1-E2E-FX-01B.6B.5B.4A: Canonical AE NSL Wheel Packaging Reconciliation`,
which must align the generic nine-image builder with the already admitted AE
NSL packaging contract and restore a complete release-set package matrix.
