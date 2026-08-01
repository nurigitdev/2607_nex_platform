# Design System Skeleton

Status: Draft bootstrap.

The design system should keep NeX-Platform screens consistent while the services
split apart. Bootstrap can remain the implementation baseline, but NeX-specific
tokens and components should be documented before the UI grows further. The MVP
expansion is now assembled in
[Design System v0.1 Expansion](../../35_design_system_v0_1_expansion.md).

## Design Principles

| Principle | Meaning |
| --- | --- |
| Work-first density | Operational screens should prioritize scanning, comparison, filtering, and repeated action. |
| Evidence visible | Search, generation, and operations screens should expose source, status, and confidence metadata. |
| Calm hierarchy | Use restrained type, spacing, and color so tables, panels, and controls stay readable. |
| Korean default | Korean is the default interface language; English is available through the same i18n keys. |
| Accessible controls | Buttons, tabs, menus, toggles, inputs, and status badges should remain keyboard and screen-reader friendly. |

## Design Tokens

| Token Group | Initial Direction |
| --- | --- |
| Color | Neutral base, semantic status colors, restrained accents for primary actions. |
| Typography | Bootstrap-compatible scale with compact dashboard headings and readable body text. |
| Spacing | 4/8px rhythm for dense operations surfaces and form controls. |
| Radius | 8px or less for cards and panels unless component semantics require less. |
| Shadow | Minimal; use borders and spacing before decorative elevation. |
| Status | Success, warning, danger, info, muted, pending, running, blocked. |

## Component Library Skeleton

| Component | Primary Use |
| --- | --- |
| App shell | Left navigation, top status area, content workspace. |
| Data table | Inventories, logs, histories, provider routes, benchmark runs. |
| Filter bar | Time windows, service filters, quality filters, tokenizer/profile selectors. |
| Status badge | Provider health, readiness, generation quality, queue state. |
| Detail drawer/panel | Logs, diffs, source context, retrieval package, quality evidence. |
| Upload dropzone | Document ingestion with drag-and-drop and progress feedback. |
| Chat workspace | Conversation, intent mode, citations, artifacts, retry/edit lineage. |
| Artifact preview | Markdown/docx/pdf preview and download shortcut. |
| Metric card | Dashboard summary, vLLM readiness, provider memory share. |
| Confirmation modal | Risky admin and governance changes. |

## Service-Specific UI Surfaces

| Surface | Service | Notes |
| --- | --- | --- |
| User workspace | `nex-ae-web` | Chat, search, generation, summary, artifact preview. |
| Retrieval context | `nex-ae-web` + `nex-cx` | Show source anchors, chunks, scores, policy, and no-answer state. |
| Provider operations | `nex-mo` + `nex-ag` | Health, metrics, resource usage, contracts, route activation. |
| Admin & governance | `nex-ag` | Logs, audit, policy, retention, readiness, exports. |
| Auth settings | `nex-oa` + `nex-ag` | Roles, claims, service principals, API keys, trust boundary evidence. |

## Documentation To Add Later

- Token values with CSS variable names.
- Component states and accessibility notes.
- Page-level IA for user, operator, and administrator scenarios.
- Screenshot-based UI acceptance evidence.
- Korean and English copy glossary.
