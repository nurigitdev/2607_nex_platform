import { DEFAULT_LOCALE, message } from "../locales/messages.js";
import type { StatusTone } from "../design-system/components/status";

export const WORK_STATES = Object.freeze(
  [
    "requested",
    "in_progress",
    "waiting_approval",
    "completed",
    "failed",
    "cancelled",
  ] as const,
);

export type WorkState = (typeof WORK_STATES)[number];
export type WorkStateTone = StatusTone;
export type WorkStateIconRole =
  | "request"
  | "progress"
  | "approval"
  | "success"
  | "error"
  | "cancelled"
  | "unknown";
export type WorkStateActionKind =
  | "review_request"
  | "view_progress"
  | "review_approval"
  | "view_result"
  | "retry";

export interface WorkStateDefaultAction {
  readonly kind: WorkStateActionKind;
  readonly labelKey: string;
  readonly label: string;
}

export interface WorkStatePresentation {
  readonly state: WorkState | "unknown";
  readonly known: boolean;
  readonly labelKey: string;
  readonly label: string;
  readonly ariaLabel: string;
  readonly tone: WorkStateTone;
  readonly iconRole: WorkStateIconRole;
  readonly terminal: boolean | null;
  readonly defaultAction: WorkStateDefaultAction | null;
  readonly technicalDetailRef: "UX_STATE_UNRECOGNIZED" | null;
}

interface WorkStateDefinition {
  readonly labelKey: string;
  readonly tone: WorkStateTone;
  readonly iconRole: Exclude<WorkStateIconRole, "unknown">;
  readonly terminal: boolean;
  readonly defaultAction: Readonly<{
    kind: WorkStateActionKind;
    labelKey: string;
  }> | null;
}

const WORK_STATE_DEFINITIONS: Readonly<Record<WorkState, WorkStateDefinition>> =
  Object.freeze({
    requested: definition(
      "ux.work_state.requested",
      "neutral",
      "request",
      false,
      "review_request",
      "action.review_request",
    ),
    in_progress: definition(
      "ux.work_state.in_progress",
      "info",
      "progress",
      false,
      "view_progress",
      "action.view_progress",
    ),
    waiting_approval: definition(
      "ux.work_state.waiting_approval",
      "warning",
      "approval",
      false,
      "review_approval",
      "action.review_approval",
    ),
    completed: definition(
      "ux.work_state.completed",
      "success",
      "success",
      true,
      "view_result",
      "action.view_result",
    ),
    failed: definition(
      "ux.work_state.failed",
      "danger",
      "error",
      true,
      "retry",
      "action.retry",
    ),
    cancelled: definition(
      "ux.work_state.cancelled",
      "neutral",
      "cancelled",
      true,
    ),
  });

const WORK_STATE_SET: ReadonlySet<string> = new Set(WORK_STATES);

export function mapWorkState(
  internalState: unknown,
  locale = DEFAULT_LOCALE,
): WorkStatePresentation {
  const state = normalizeWorkState(internalState);
  if (state === null) return unknownPresentation(locale);

  const definition = WORK_STATE_DEFINITIONS[state];
  const label = message(definition.labelKey, { locale });
  return Object.freeze({
    state,
    known: true,
    labelKey: definition.labelKey,
    label,
    ariaLabel: label,
    tone: definition.tone,
    iconRole: definition.iconRole,
    terminal: definition.terminal,
    defaultAction: presentDefaultAction(definition.defaultAction, locale),
    technicalDetailRef: null,
  });
}

export function isWorkState(value: unknown): value is WorkState {
  return typeof value === "string" && WORK_STATE_SET.has(value);
}

function normalizeWorkState(value: unknown): WorkState | null {
  if (typeof value !== "string") return null;
  const candidate = value.trim().toLowerCase();
  return WORK_STATE_SET.has(candidate) ? (candidate as WorkState) : null;
}

function definition(
  labelKey: string,
  tone: WorkStateTone,
  iconRole: Exclude<WorkStateIconRole, "unknown">,
  terminal: boolean,
  actionKind?: WorkStateActionKind,
  actionLabelKey?: string,
): WorkStateDefinition {
  const defaultAction =
    actionKind && actionLabelKey
      ? Object.freeze({ kind: actionKind, labelKey: actionLabelKey })
      : null;
  return Object.freeze({ labelKey, tone, iconRole, terminal, defaultAction });
}

function presentDefaultAction(
  action: WorkStateDefinition["defaultAction"],
  locale: string,
): WorkStateDefaultAction | null {
  if (action === null) return null;
  return Object.freeze({
    kind: action.kind,
    labelKey: action.labelKey,
    label: message(action.labelKey, { locale }),
  });
}

function unknownPresentation(locale: string): WorkStatePresentation {
  const labelKey = "ux.work_state.unknown";
  const label = message(labelKey, { locale });
  return Object.freeze({
    state: "unknown",
    known: false,
    labelKey,
    label,
    ariaLabel: label,
    tone: "neutral",
    iconRole: "unknown",
    terminal: null,
    defaultAction: null,
    technicalDetailRef: "UX_STATE_UNRECOGNIZED",
  });
}
