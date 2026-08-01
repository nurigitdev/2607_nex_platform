# Documentation Framework

Status: Draft bootstrap.

## Purpose

The NeX-Platform documentation set should help build a minimum viable platform
within a short execution window while preserving the hard-won learning from
NeX-PCX. The docs should keep service boundaries clear, avoid over-designing
before implementation starts, and make deferred decisions explicit.

NeX-PCX source code direct reuse is not the primary goal. NeX-PCX is treated as
an evidence source: it shows which workflows were useful, which risks appeared
in operation, which APIs were stable enough to keep, and which concerns should
move into dedicated services.

## Documentation Principles

| Principle | Meaning |
| --- | --- |
| Minimum useful set | Start with the fewest documents that unblock SRS, design, development, and testing. |
| Evidence over memory | Prefer PCX docs, migration history, tests, screenshots, smoke evidence, and commits over recollection. |
| Service ownership first | Every requirement should have one clear owning service and known consumers. |
| MVP/defer discipline | Separate the 2-week MVP from later platform hardening. |
| Contract before UI polish | Stabilize API, auth, data, and provider contracts before expanding visual detail. |
| Korean default, English-ready | Korean is the default UI/documentation language, but key identifiers and APIs remain English. |

## Source Material Hierarchy

Use this order when sources conflict:

1. Confirmed operational facts from NeX-PCX runtime, database state, smoke output,
   and regression tests.
2. Committed NeX-PCX SRS, design docs, migrations, and API contracts.
3. User-confirmed platform boundaries and current business intent.
4. Reduced 2-week MVP document.
5. Large 400,000-token design document, distilled through the review matrix.
6. Assistant inference, clearly marked as inference.

## Review Phases

| Phase | Output |
| --- | --- |
| Inventory | Register source documents and identify relevant sections. |
| Distill | Extract claims, requirements, constraints, and open questions. |
| Map | Assign each item to `nex-cx`, `nex-ae-web`, `nex-ae-api`, `nex-mo`, `nex-oa`, or `nex-ag`. |
| Decide | Mark each item as MVP, deferred, rejected, duplicate, or needs review. |
| Normalize | Convert accepted items into SRS, design, environment, testing, or common module docs. |
| Trace | Preserve links to PCX evidence, source sections, and commit references. |

## Minimum Document Set

| Document | Required Before Build? | Purpose |
| --- | --- | --- |
| Service Boundary | Yes | Prevent cross-service drift and duplicate ownership. |
| MVP SRS | Yes | Define the smallest product that can be built and tested. |
| Design System | Yes | Keep AE/AG/MO screens coherent from the first UI slice. |
| Development Environment | Yes | Make local, test, and deployment assumptions reproducible. |
| Testing Strategy | Yes | Keep regression and coverage gates clear from day one. |
| Common Modules | Yes | Identify shared contracts without prematurely creating shared libraries. |
| Review Matrix | Yes | Provide the intake lane for the 400,000-token and 2-week documents. |
| Source Material Inventory | Yes | Register uploaded source files, hashes, review priority, and conflict notes without committing raw source files. |

## Definition of Done for Documentation Slices

- Each new requirement has an owner service.
- MVP vs deferred status is explicit.
- Security and trust boundary impacts are called out when relevant.
- Testing implications are recorded.
- Operational evidence or required future evidence is listed.
- The document can be tested with lightweight doc-contract tests.
- Raw source material stays in `artifacts/nex-platform/source-materials/` unless the user explicitly approves committing it.
