# P9-S19: Human READY Artifact Admission

## Scope

NeX-WA now admits an authoritative NeX-AE `READY` Artifact version as Human
work evidence. Admission requires exact tenant, Artifact, version, and content
hash agreement with the intake request. The Artifact owner is verified through
NeX-OA before any WA state is written.

Project attribution remains source-authoritative:

- no `project_ref` means WA does not infer a Project;
- a supplied `project_ref` requires NeX-EOS historical membership verification
  at the Artifact creation time;
- unavailable verification is retryable, while mismatched authority fails
  closed without partial admission.

The admitted shape is one `HUMAN_OWNED_ARTIFACT` WorkAsset with one PRIMARY
`OWNERSHIP_OR_DELIVERABLE_EVIDENCE` WorkEvidence. An Agent producer reference
does not convert Human ownership into Agent attribution or Human effort credit.
Human evidence is at least `CONFIDENTIAL`, and an existing `RESTRICTED`
classification is preserved.

## Contract

The protected AE Artifact projection now carries nullable `project_ref`.
This field is an authoritative source value and is not reconstructed by WA.
The existing Artifact source endpoint and schema version remain unchanged.

## Verification

Tests cover READY admission, OA owner rejection, EOS historical membership,
project-neutral evidence, Agent-producer separation, classification floors,
projection drift, malformed values, and all three protected HTTP clients.

- Focused adapter regression: `19 passed`
- Contract validation: `31 passed`
- NeX-WA Slice Gate: passed
- WA aggregate coverage: statement `97.58%`, branch `94.85%`
- New Artifact source adapter: statement `100%`, branch `100%`
- Ruff and repository diff hygiene: passed

Actual AE/OA/EOS/WA PostgreSQL and signed-token execution remains assigned to
the P9-CA03 protected gate after P9-S20.
