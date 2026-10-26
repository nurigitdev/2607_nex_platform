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

## Focused Regression

```text
AE Web Node tests       = 398 passed
S11 Python tests        = 10 passed
AE Web static tests     = 28 passed
syntax / diff checks    = PASS
```

Actual PostgreSQL, live generation, Playwright, screenshot, and restart
results are recorded after rebuilding the installed release images.
