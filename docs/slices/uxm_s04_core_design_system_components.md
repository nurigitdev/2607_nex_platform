# UXM-S04 Core Design System Components

## Outcome

PASS. The React v2 design-system foundation is ready for shell and Approval UI
implementation.

## Components

```text
Button / IconButton
Input / Select / Textarea / Checkbox / Radio
Badge / StatusPill / Toast / Stepper
Card / Table / List
Tabs / NavItem
Drawer / Modal / ConfirmDialog / Tooltip
EmptyState / Avatar
```

## Implementation Decisions

- Components use CSS Modules and canonical S03 variables; component-local
  colors are prohibited by test.
- Lucide supplies interface icons.
- Radix supplies Tabs, Dialog, AlertDialog, and Tooltip interaction semantics.
- Icon-only commands require an explicit accessible label.
- Status components retain both an icon and visible text.
- Modal, drawer, and confirmation focus/Escape behavior is delegated to
  established accessible primitives.
- Cards use the 8px design-token radius and are not nested by the primitives.

## Verification

```text
npm run typecheck:v2 = PASS
npm run test:react   = PASS, 28 tests
npm run tokens:check = PASS
npm run build:v2     = PASS
npm test             = PASS, 404 tests
```

Tests cover rendering, keyboard interaction, focus, disabled/loading states,
accessible names and descriptions, variants, status meaning, modal Escape,
confirmation, data semantics, dark token availability, and component-local
color rejection.

## Decision

```text
UXM-S04 = PASS / CLOSED
FOUNDATION_CHECKPOINT_1 = AUTHORIZED
```
