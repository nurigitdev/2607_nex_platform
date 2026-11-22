# NeX MyBee W80-CA00 Platform Diagnostic Logging and Live-Journey Evidence Boundary v1.0

**Status:** CONTROLLED AMENDMENT / IMPLEMENTED

**Boundary:** W70 M1 As-Built -> W80-CA01 entry

**Schema or public API change:** None

## 1. Purpose

W70 M1 live acceptance exposed that container output alone is insufficient to
diagnose a multi-service Agent journey. W80-CA00 establishes a platform-wide,
restricted diagnostic-evidence boundary before W80 accounting work begins.

This amendment does not change business authority or persist another business
record. It separates ordinary operational logs from an explicitly enabled
live-journey evidence set that can contain the raw Agent data needed to explain
planning and execution failures.

## 2. Required Diagnostic Content

When `LIVE_JOURNEY` evidence is explicitly enabled, the evidence set must
include, where the corresponding stage is reached:

1. the user's `raw_prompt` or `user_prompt`;
2. WorkIntent and admitted Agent context;
3. provider request/response and candidate data;
4. internal plan candidate, AgentPlan, PlanValidation, and ExecutablePlan;
5. RuntimeJob authority, executable step input, step result, and step output;
6. cross-service HTTP query, JSON/text request, response, status, and timing;
7. process/container logs for every installed service and worker in the live
   journey;
8. correlation identities such as request, interaction, execution, and
   RuntimeJob IDs.

Omitting raw prompt or plan data from a DEBUG live journey is not accepted.
These values are necessary diagnostic evidence, not ordinary service-log
attributes.

## 3. Two Logging Planes

| Plane | Default | Content | Storage |
| --- | --- | --- | --- |
| operational log | enabled | lifecycle, health, typed failures, safe identifiers | Docker `local` log driver |
| restricted diagnostic evidence | `OFF` | metadata or admitted raw Agent/API/execution data | dedicated private volume and extracted report set |

`services/_shared/nex_runtime/service_logs.py` remains the safe operational
logging contract. Raw prompt and plan values must not be added to that table or
its normal projections.

## 4. Admission Modes

The canonical modes are:

- `OFF`: no diagnostic evidence is written;
- `METADATA`: raw fields are replaced by an omission marker and digest;
- `LIVE_JOURNEY`: raw structured content is admitted only when
  `NEX_DIAGNOSTIC_EVIDENCE_INCLUDE_RAW=true` is also supplied.

An enabled mode requires a dedicated root and a valid session ID. Invalid mode,
missing root, missing session, excessive retention, or LIVE mode without the
explicit raw switch fails configuration admission.

## 5. Secret and Binary Boundary

Passwords, Authorization headers, cookies, API/client secrets, database URLs,
private keys, access/refresh/service/lease/resume tokens, and equivalent nested
fields are always redacted. DEBUG is not an exception to credential hygiene.

JSON, URL-encoded form data, and text may be retained in the restricted
evidence set. Multipart and binary bodies are represented by content type,
size, and SHA-256 rather than raw bytes. This preserves attachment identity
without duplicating private documents into logs.

## 6. Integrity and Filesystem Controls

Each component writes process-scoped JSONL evidence with:

- mode `0600` files under mode `0700` session directories;
- monotonic sequence, previous-event hash, and event hash;
- payload digest and explicit raw/redacted path inventory;
- a final recursive file manifest with file size, mode, and SHA-256;
- a default retention declaration of seven days and an absolute maximum of
  thirty days.

Evidence is copied from the running AE diagnostic volume before Compose removes
ephemeral volumes. Generated evidence under `reports/` remains untracked release
evidence and must not be committed.

## 7. Docker and Installed Journey Boundary

Canonical Compose applies the Docker `local` log driver to every installed
service with bounded rotation (`20m`, ten files, compression by default).
Python APIs and worker processes share a private diagnostic volume. The live M1
runner enables one unique evidence session, collects all installed process logs
and restricted JSONL files before teardown, and creates the final manifest.

Ordinary startup leaves diagnostic mode `OFF`; therefore this amendment does
not continuously retain raw user or Agent data.

## 8. Product Instrumentation

The shared FastAPI shell captures admitted HTTP exchanges for OA, AE, CX, MO,
AG, WC, EOS, and WA. The AE semantic admission path records raw prompt,
candidate, WorkIntent, AgentPlan, validation, and ExecutablePlan. The installed
AE runtime handler records step start, completion, failure, RuntimeJob authority,
compiled step input, and durable step result.

Instrumentation is scenario-neutral. It contains no M1 tenant, Project,
operation, fixed identifier, or fixture branch.

## 9. Acceptance

W80-CA00 requires focused proof of:

1. default no-op behavior;
2. unsafe configuration rejection;
3. raw Agent data presence in LIVE mode;
4. raw omission in METADATA mode;
5. recursive secret redaction;
6. HTTP JSON/text capture and multipart opacity;
7. runtime step input/output capture;
8. hash-chain and corrupt-tail rejection;
9. manifest, file-mode, Compose logging, and pre-teardown collection behavior;
10. no migration, public API, or business-authority change.

No remote provider is required for source admission of this boundary. The
post-implementation protected journey was run with LIVE evidence enabled from
exact commit `95fd485717ed673e7b574a7da7b184c5dc90c7fa`. Actual PostgreSQL,
OpenBao, RustFS, Qwen3.5-9B generation, authenticated Playwright, restart
recovery, and zero-residue cleanup all passed.

The protected session produced 25 manifest files and 5,878 diagnostic events,
including 5,836 HTTP exchanges, 12 admitted semantic candidates, two compiled
ExecutablePlans, and ten completed runtime steps. Presence checks passed for
raw prompt, AgentPlan, and ExecutablePlan. Recursive redaction recorded 10,166
secret paths across 4,718 events; direct scans found no admitted API key,
database password, Bearer token, or Authorization value. The protected
manifest digest is
`7f5012c04ea6608dc02e50f2681f3644231340a815881a1bbf8851803bd8949b`.
Raw evidence remains ignored under `reports/` and is not part of this baseline.

The authoritative AE Slice Gate completed `6,917` tests with `53` protected
smokes skipped and retained statement/branch coverage at `96.45%`/`94.67%`.
Focused W80-CA00 regression completed `121` tests. The broad shared-runtime
diagnostic profile completed `2,151` tests with one protected PostgreSQL skip;
both new diagnostic modules reached `100%` statement and branch coverage. Its
historical aggregate remains non-authoritative because the profile selects
unowned shared source modules, producing `87.06%`/`84.15%` against the global
thresholds. This existing scope mismatch is not attributed to W80-CA00.

## 10. Decision

```text
W80-CA00 DIAGNOSTIC BOUNDARY = IMPLEMENTED
RAW PROMPT / PLAN EVIDENCE   = REQUIRED IN LIVE_JOURNEY
SECRETS IN EVIDENCE          = FORBIDDEN
DEFAULT RAW COLLECTION       = OFF
BUSINESS AUTHORITY CHANGE    = NONE
NEXT BOUNDARY                = W80-CA01
```
