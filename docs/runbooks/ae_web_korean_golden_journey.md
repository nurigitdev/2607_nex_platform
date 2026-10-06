# AE Web Korean Golden Journey Runbook

## Preconditions

- Use only the OA, AE, and CX test database profiles for protected execution.
- Apply the current OA, AE, and CX migrations before starting browser evidence.
- Ensure local Chromium and the AE Web Node dependencies are installed.
- Keep the deterministic MO mock capability available. Remote provider
  execution is not part of S139 because S136 and S137 own that evidence.
- The browser must call only the same-origin `/ae-api` facade. It must not call
  OA, CX, MO, AG, a database, or private storage directly.

## Deterministic Command

Start the AE Web development server in its local mock profile, then run:

```bash
npm run smoke:korean-golden-journey-playwright --prefix apps/nex-ae-web
```

Confirm both frozen viewports complete the same nine-stage Korean journey and
that the generated screenshots remain under the ignored quality-report path.

## Protected Command

Provide the three service-local test database URL environment values through
the local secret mechanism, set `NEX_S139_AE_WEB_PROTECTED_ACCEPTANCE=1`, and
run:

```bash
./.venv/bin/python scripts/smoke/run_s139_ae_web_protected_acceptance.py --summary
```

Do not place connection strings, credentials, tokens, or provider endpoints in
shell history, evidence documents, issue comments, or committed configuration.

## Expected Evidence

The successful protected summary is:

```text
s139_ae_web_protected_acceptance=pass sources=5/5 db=3 processes=13 viewports=2 next=1391
```

Confirm the process topology, OA-backed login, owner-scoped upload, grounded
artifact delivery, and two-viewport browser sources all report `PASS`. Confirm
the nine journey stages, thirteen stopped processes, three exact test database
identities, and zero protected fixture residue.

## Failure Triage

- For login failures, check OA migration state, credential fixture admission,
  same-origin proxying, secure session projection, and logout revocation.
- For upload failures, check claim-derived owner headers, multipart hash/size,
  shared upload-handoff storage, and the owner-scoped progress route.
- For generation or artifact failures, check AE/CX migration state, retrieval
  readiness, citation workflow, response lineage, render worker result, and
  artifact-file access.
- For layout failures, inspect the exact failing viewport, target-size count,
  horizontal overflow, focus visibility, non-overlap pair, and page errors.
- Do not replace a failed owner check with browser-supplied ownership. Identity,
  ownership, citation, and artifact access must fail closed.

## Screenshot And Viewport Verification

Require desktop `1440x900` and mobile `390x844` screenshots from the same DOM
and semantic journey. Each viewport must have one main landmark, one H1, all
nine regions, Korean-default labels, named controls, visible focus, no
horizontal overflow, and zero overlap for the frozen primary-region pairs.
Screenshots are visual evidence only and must not be parsed as business data.

## Cleanup Verification

The protected runner deletes its temporary OA, AE, and CX fixtures and stops
all API, Web, worker, daemon, and browser processes. Every reported AE/CX
owner-scoped residue counter must be zero. If a run fails, rerun only after
confirming no prior process or protected fixture remains; never delete unrelated
test records.

## Rollback And Fail-Closed

- Disable protected execution by removing its opt-in flag.
- Keep the deterministic browser suite and last accepted redacted evidence
  active while diagnosing a protected dependency.
- Do not bypass authentication, owner scope, retrieval admission, citation
  validation, artifact lineage, or cleanup checks.
- Preserve the Korean-default catalog and same semantic desktop/mobile journey
  when reverting an individual browser surface.

## Privacy And Secret Handling

Browser and operator evidence may retain bounded states, counts, viewport
dimensions, safe routes, screenshot references, and hashes of opaque
identifiers. It must not retain passwords, tokens, prompts, source or evidence
text, generated text, structured drafts, file payloads, storage references,
database locations, provider endpoints, absolute paths, or private keys.

## S140 Handoff

S140 receives the repeatable deterministic and protected browser commands,
redacted correlation evidence, screenshot rules, and zero-residue cleanup
expectation. S140 owns the release-candidate matrix across all five test
databases, all three live provider capabilities, restart and recovery, privacy,
contracts, Full Gate, and explicit deployment deferrals.
