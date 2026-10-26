# P8-DEMO-S11: Protected Installed Chairman Golden Journey Acceptance

## Outcome

The installed Chairman Demo journey is accepted on the single-host Docker
Compose topology. The Slice composes the existing P6-P8 runtime rather than
introducing a parallel planner, worker, approval path, or business write path.

```text
OA browser login
-> AE workspace and live semantic planning through MO
-> durable Agent execution and multi-step scheduling
-> NSL WRITE approval checkpoint
-> WC approval decision and resume
-> EOS controlled voucher write
-> deterministic report and AgentResult finalization
-> WORKSPACE_RESULT publication and ACK
-> owner-scoped AE Web result
-> service restart and authoritative browser recovery
```

The protected acceptance used all seven development PostgreSQL databases,
OpenBao, RustFS, Traefik, Docker Compose, the live DGX generation provider,
and Playwright Chromium. Embedding and reranking were outside this journey.

## Runtime Closure

The installed path now proves:

- the active `FINANCE.CREATE_VOUCHER_DRAFT` capability compiles and dispatches;
- all admitted executor kinds are available to the installed AE worker;
- a completed non-waiting step schedules the next existing plan step;
- OA approval-authority reads use signed service trust with the required scope;
- WC approval resumes the same execution into the controlled EOS WRITE;
- `RESULT_VERIFY` uses `SqlAlchemyP5PlanFinalizationService`;
- `WORKSPACE_RESULT` is published once, acknowledged, and owner-scoped;
- a restart reloads the same result without another voucher or AgentResult;
- browser logout is authoritative and returns both sessions to the login view.

No database migration or new business table was required by S11.

## Live Evidence

```text
status                         = PASS
actual PostgreSQL              = true
actual remote generation       = true (Qwen3.5-4B)
actual Playwright              = true
actual OpenBao / RustFS        = true / true
database migrations current    = 7 / 7 services
execution terminal             = SUCCEEDED / FINALIZE
AgentResult                    = 1
WORKSPACE_RESULT delivery      = 1 ACKNOWLEDGED
approval decision              = 1
EOS BusinessOperation          = 1
voucher / balanced lines       = 1 / 2
post-restart duplicates        = 0
post-restart pending queues     = AE 0 / WC 0 / EOS 0
```

The restart recovery preserved the result hash and business references. The
runner cleaned tenant fixtures, temporary service principals, credentials,
signing keys, sessions, and Compose containers in its protected finalizer.
Secret values, database URLs, passwords, prompts, and provider payloads are
not included in the evidence report.

## Screen Evidence

> Follow-up: P8-DEMO-S11A replaced the static fetch-mode Chat/RAG sample with
> the prompt-first Golden A journey. The filenames and visual observations in
> this section preserve the original S11 evidence; current evidence is listed
> in `p8_demo_s11a_prompt_first_golden_a_browser_journey.md`.

Playwright now clears the prior S11 capture set and records every meaningful
view transition without entering credentials before the login capture. Nine
primary journey screens and two restart-recovery screens were saved:

```text
reports/deployment/p8-demo-s11-screens/
  p8-demo-s11-journey-01-login.png
  p8-demo-s11-journey-02-requester-workspace.png
  p8-demo-s11-journey-03-approver-workspace.png
  p8-demo-s11-journey-04-approval-inbox.png
  p8-demo-s11-journey-05-approval-detail.png
  p8-demo-s11-journey-06-approval-decided.png
  p8-demo-s11-journey-07-requester-result.png
  p8-demo-s11-journey-08-approver-logged-out.png
  p8-demo-s11-journey-09-requester-logged-out.png
  p8-demo-s11-recovery-01-requester-workspace.png
  p8-demo-s11-recovery-02-requester-result.png
```

Visual inspection confirmed that the login, approval, result, and logout
states render without overlap. The existing static Chat/RAG sample content is
still visible above the installed work-result projection; that presentation
cleanup is Demo UI polish and does not affect the accepted runtime contract.

## OCI Evidence

The eight-image local release set and enriched AE runtime image were rebuilt
from the accepted source without registry push.

```text
application images        = 8 / 8
release set digest        = sha256:b35c14328a92db975dca556ab05e24150bb22a356c4fb9e8baff9f465f27c3b3
AE runtime image id       = sha256:ca9a392a7912b9f20a36d71d1db788aecfa35f67e01b69f8dcca39883b2e2530
runtime user              = 65532:65532
packaged NSL version      = 0.2.1
packaged Skill            = FINANCE.VOUCHER_DRAFT_CREATE / 1.1.0
```

## Regression Reconciliation

The first Full Gate exposed historical test baselines that had not yet
absorbed the installed Demo changes. The closure made the following bounded
corrections:

- the legacy workspace SQLite smoke now includes `ae_conversations`;
- the P6.5 intent smoke derives the active prompt version from the registry
  seed instead of pinning historical `v6`;
- the owner-scoped AgentResult route is documented in AE OpenAPI;
- OA migration expectations are calculated from the migration inventory;
- reduced OA contract drift is accepted as monotonic hardening instead of
  requiring the historical value `21`.

Focused regression after reconciliation: `91 passed`.

## Full Gate

```text
Repository regression     = 17,824 passed / 118 protected skips
statement coverage        = 96.01% / required 96.00%
branch coverage           = 95.27% / required 94.00%
contract validation       = PASS
contract inventory        = 207 schemas / 271 examples / 231 negative / 9 OpenAPI
Full Gate exit             = 0
```

Runtime evidence remains in ignored reports:

- `reports/deployment/p8-demo-s11-chairman-golden-journey.json`
- `reports/deployment/p8-demo-oci-image-build.json`
- `reports/deployment/p8-demo-ae-runtime-image.json`
- `reports/deployment/p8-demo-s11-screens/*.png`
- `reports/coverage/coverage.json`
- `reports/coverage/junit.xml`

## Closure

P8-DEMO-S11 is complete. The installed Chairman Golden Journey now proves
authenticated live planning, human approval, controlled EOS commit, durable
result publication, owner-scoped browser presentation, restart recovery,
exactly-once business effects, and screen-by-screen visual evidence.
