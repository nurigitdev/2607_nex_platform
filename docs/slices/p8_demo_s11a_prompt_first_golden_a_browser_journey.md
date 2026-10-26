# P8-DEMO-S11A: Prompt-First Golden A Browser Journey

## Decision

The Chairman Golden A journey starts with the voucher request itself. Document
upload and RAG remain available product capabilities, but neither a mock RAG
conversation nor a completed mock generation timeline may appear before the
requester submits the Golden A prompt.

```text
OA login
-> empty authenticated Chat/Workspace
-> enter voucher request in the visible composer
-> disable document retrieval for this business command
-> submit through the visible Send control
-> live semantic planning
-> NSL WRITE approval
-> controlled EOS voucher commit
-> owner-scoped result presentation
```

The Slice does not remove upload, document, retrieval, or artifact functions.
Those capabilities remain available from their authenticated navigation views.

## Implementation

- Fetch-mode AE Web state no longer inherits mock documents, messages,
  artifacts, audit results, or a completed RAG timeline.
- Mock mode retains the historical sample state for isolated UI regression.
- The composer no longer contains a prefilled report prompt.
- A submitted prompt is rendered immediately and the composer is cleared.
- The S11 Playwright runner creates the durable workspace, installs its
  browser bootstrap, types the canonical voucher prompt, disables retrieval,
  and clicks the visible Send button.
- A compiled semantic Agent plan is handed to the AgentResult lifecycle. It
  does not continue through the response/citation polling path owned by
  ordinary Chat/RAG generation.
- The pending AgentResult card is updated in place at terminal completion and
  drives the workspace and generation-control status to `COMPLETED` without
  adding a duplicate card or retaining a stale `PENDING` indicator.
- Screen evidence includes the empty workspace, prompt-ready state, and
  prompt-submitted state in addition to approval, result, logout, and restart
  recovery transitions.

## Acceptance

The browser runner must derive all prompt-first checks from the DOM:

- zero initial chat messages;
- one idle timeline event;
- an initially empty composer;
- a non-empty composer before submission;
- retrieval disabled before and after submission;
- exactly one visible user message and an empty composer after submission;
- the interaction ID returned by that browser submission drives approval,
  EOS commit, AgentResult publication, and restart recovery.

An initial protected run correctly failed the new presentation checks because
Compose reused the previous immutable AE Web image. This is an expected
fail-closed result: the current eight-image release set and enriched AE runtime
image must be rebuilt before the protected acceptance is repeated.

Visual inspection of the first rebuilt run found a second fail-closed issue:
the business execution and EOS commit succeeded, but the legacy generation
poller subsequently marked the browser surface failed. The semantic planning
handoff above closes that split-brain presentation without changing the RAG
workflow.

## Focused Regression

```text
AE Web Node tests       = 400 passed
S11 Python tests        = 10 passed
AE Web static tests     = 28 passed
syntax / diff checks    = PASS
```

Actual PostgreSQL, live generation, Playwright, screenshot, and restart
results passed after rebuilding the installed release images.

## Protected Live Evidence

```text
status                         = PASS
actual PostgreSQL              = true (7 dev databases current)
actual remote generation       = true (Qwen3.5-4B)
actual Playwright              = true
browser checks                 = 24 / 24
initial / submitted messages   = 0 / 1
initial timeline events        = 1
execution                      = SUCCEEDED / FINALIZE
AgentResult / delivery ACK     = 1 / 1
approval / business operation  = 1 / 1
voucher / balanced lines       = 1 / 2
post-restart pending queues     = AE 0 / WC 0 / EOS 0
screen captures                = 13
```

The browser-submitted interaction remained authoritative through semantic
planning, approval, EOS commit, result publication, logout, service restart,
and recovery. The final visual inspection showed one user prompt, one updated
AgentResult card, `COMPLETED` workspace state, `SUCCEEDED` generation control,
and a `FINALIZE` timeline without the historical RAG sample.

## Screen Evidence

```text
reports/deployment/p8-demo-s11-screens/
  p8-demo-s11-journey-01-login.png
  p8-demo-s11-journey-02-requester-workspace-empty.png
  p8-demo-s11-journey-03-voucher-prompt-ready.png
  p8-demo-s11-journey-04-voucher-prompt-submitted.png
  p8-demo-s11-journey-05-approver-workspace.png
  p8-demo-s11-journey-06-approval-inbox.png
  p8-demo-s11-journey-07-approval-detail.png
  p8-demo-s11-journey-08-approval-decided.png
  p8-demo-s11-journey-09-requester-result.png
  p8-demo-s11-journey-10-approver-logged-out.png
  p8-demo-s11-journey-11-requester-logged-out.png
  p8-demo-s11-recovery-01-requester-workspace.png
  p8-demo-s11-recovery-02-requester-result.png
```

## OCI Evidence

```text
application images        = 8 / 8
release set digest        = sha256:d61f33c835e2e0e627cda77a3363e5b76475a790e787483d371289022e45a4c0
AE runtime image id       = sha256:9c08de993ef4ab64c7f9e116a81e244bc5ccca988f5cc9dc79086cd0d3ad34dd
runtime user              = 65532:65532
packaged NSL version      = 0.2.1
registry push             = false
```

Runtime reports and PNG files remain under ignored `reports/deployment/`.
Secrets, database URLs, passwords, raw provider payloads, and prompt text are
excluded from JSON evidence.
