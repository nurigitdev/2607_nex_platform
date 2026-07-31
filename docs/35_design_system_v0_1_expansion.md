# Design System v0.1 Expansion

Status: Draft seed for Slice 445.

Sources:

- [Design System Skeleton](03_design_system_skeleton.md)
- [Chat Workspace Artifact Link Requirements](23_chat_workspace_artifact_link_requirements.md)
- [AG Generation Artifact Audit Dashboard Requirements](25_ag_generation_artifact_audit_dashboard_requirements.md)
- [Testing Strategy v0.1 Detail](34_testing_strategy_v0_1_detail.md)
- [NeX-Platform MVP SRS v0.1 Assembly](29_nex_platform_mvp_srs_v0_1_assembly.md)

This document expands the design system skeleton into an MVP-ready UI standard
for NeX-Platform. Bootstrap can remain the implementation baseline, but
NeX-specific tokens, components, states, and evidence rules should be explicit
before AE and AG screens grow.

## Design Principles

| Principle | Rule |
| --- | --- |
| Work-first density | Screens are designed for repeated use, scanning, filtering, and comparison. |
| Evidence visible | Search, generation, artifact, and audit views show source, confidence, status, and lineage. |
| Calm hierarchy | Use restrained type, compact headings, clear tables, and semantic color rather than decorative layouts. |
| Korean default | Korean UI is primary; English is available through i18n keys. |
| Action clarity | Buttons and controls state exactly what they do and expose disabled reasons. |
| Progress honesty | Long-running jobs show real stage/status and avoid fake percentages. |
| Redaction by design | Admin views make sensitive data intentionally absent, not merely hidden by CSS. |

## Token Seed

| Token Group | MVP Values |
| --- | --- |
| Color base | `--nex-bg`, `--nex-surface`, `--nex-border`, `--nex-text`, `--nex-muted`. |
| Accent | `--nex-primary`, `--nex-primary-subtle`, `--nex-focus-ring`. |
| Status | `--nex-success`, `--nex-warning`, `--nex-danger`, `--nex-info`, `--nex-pending`, `--nex-running`, `--nex-muted-state`. |
| Typography | Bootstrap-compatible scale; compact page headings, readable table text, no viewport-scaled fonts. |
| Spacing | 4px base, 8px component rhythm, 16px section rhythm, dense table padding where scan-heavy. |
| Radius | 4px controls, 8px cards/panels maximum unless Bootstrap component requires otherwise. |
| Shadow | Minimal; prefer borders and spacing. |
| Z-index | Modal, drawer, toast, sticky header, and command palette values must be explicit. |

Do not build a one-color interface. Status, action, and evidence colors should
remain semantically distinct.

## Layout Standards

| Layout | Requirement |
| --- | --- |
| App shell | Left navigation, top context/status strip, main workspace. |
| AE workspace | Chat/message column plus contextual panels for sources, artifacts, progress, and settings. |
| AG dashboard | Dense tables/cards with filters, drilldown panels, and redacted details. |
| Detail panels | Use drawers or side panels for source context, lineage, JSON/detail, and audit evidence. |
| Tables | Stable columns, sortable headers, compact filters, empty/error/loading states. |
| Mobile | Preserve primary action and status; secondary panels can stack below. |

Avoid nested cards. Use cards for repeated items, modals, and framed tools, not
for every section.

## Component Library v0.1

| Component | Primary Surface | Required States |
| --- | --- | --- |
| App shell | AE web, AG | Active nav, collapsed nav, service/status strip. |
| Filter bar | AG, CX inventory, search history | Default, changed, invalid filter, empty result. |
| Data table | AG, inventories, provider routes | Loading, empty, sorted, filtered, error, selected row. |
| Status badge | All | Healthy, degraded, unhealthy, ready, running, pending, failed, warning. |
| Progress timeline | AE, AG | Queued, running, streaming, completed, failed, retryable. |
| Source evidence panel | AE | Score, citation, source anchor, permission summary, no-answer. |
| Chat message | AE | User, assistant, tool/progress, failed, regenerated, edited. |
| Artifact card | AE | Rendering, ready, failed, archived, deleted, warning accepted. |
| Download button group | AE | Available, unavailable, permission denied, expired link. |
| Audit detail drawer | AG | Redacted, expanded, exportable, note attached. |
| Metric card | AG/MO | Normal, warning, degraded, stale, unavailable. |
| Confirmation modal | AG/AE | Destructive, retry, repair, export, policy override. |

## Status And Badge Rules

| Status | UI Rule |
| --- | --- |
| `READY` / healthy | Use success color and concise label. |
| `DEGRADED` / warning | Use warning color and show reason text. |
| `FAILED` / unhealthy | Use danger color and expose retryability or owner. |
| `PENDING` / queued | Use muted or pending color and show queue/stage. |
| `RUNNING` | Use running/info color and show stage; use progress only when determinate. |
| `NO_ANSWER` | Treat as a valid guarded outcome, not a technical failure. |
| `LOW_CONFIDENCE` | Show caution badge and allowed next actions. |

Icons can support badges, but text labels must remain available for accessibility
and localization.

## Korean And English Copy

| Copy Area | Rule |
| --- | --- |
| Message keys | Use stable keys such as `generation.status.running` instead of hard-coded service text. |
| Korean default | Korean labels are primary in screenshots and default runtime. |
| English support | English copy should preserve technical terms such as chunk, embedding, reranker, artifact. |
| Error display | Show user-safe message, stable error code, and request ID for support. |
| Admin detail | Prefer concise Korean labels with raw enum/code shown in monospace. |

## Accessibility

| Area | Requirement |
| --- | --- |
| Keyboard | Navigation, filters, chat input, preview, download, retry, and drawer close must be keyboard reachable. |
| Focus | Visible focus ring for all interactive controls. |
| Tables | Headers, sort state, row actions, and empty/error states are announced where practical. |
| Status | Color is never the only status signal. |
| Progress | Long-running status changes should be announced in the UI layer where supported. |
| Downloads | Buttons include format and availability text. |

## UI Acceptance Evidence

| Surface | Required Screenshot |
| --- | --- |
| AE chat generation | Prompt, progress, answer, citation/source context, artifact card. |
| AE upload/search | Upload progress, search results, source panel, no-answer/low-confidence state. |
| AG operations | Service readiness, provider status, metrics, recent failures. |
| AG generation audit | Timeline, artifact lineage, redaction, provider usage, operator note. |

Screenshots should use Korean default and deterministic mock data unless the
slice is explicitly live-smoke oriented.

## Anti-Patterns

- Do not create marketing-style landing pages for operational tools.
- Do not hide citations, confidence, or validation warnings behind clean output.
- Do not rely only on color to communicate state.
- Do not expose raw provider URLs, model paths, prompts, or filesystem paths in
  UI details.
- Do not make every section a card.
- Do not scale font size by viewport width.

## Next Inputs

This design expansion should feed:

- First sprint backlog and UI bootstrap tasks, starting from
  [Implementation Roadmap + First Sprint Backlog](36_implementation_roadmap_first_sprint_backlog.md).
- AE workspace page-level information architecture.
- AG dashboard page-level information architecture.
- Playwright screenshot acceptance plan.
