import { DEFAULT_LOCALE, message } from "../locales/messages.js";
import type { StatusTone } from "../design-system/components/status";

export const WORK_STATES = Object.freeze(
  [
    "IDLE",
    "ACCEPTING",
    "PLANNING",
    "RUNNING",
    "WAITING_APPROVAL",
    "RESUMING",
    "VERIFYING",
    "SUCCEEDED",
    "PARTIAL",
    "FAILED",
    "CANCELLED",
  ] as const,
);

export const WORK_STATE_SOURCES = Object.freeze(
  [
    "AgentExecution",
    "GenerationLifecycle",
    "Approval",
    "ResultDelivery",
    "Artifact",
    "OperationState",
  ] as const,
);

export type WorkState = (typeof WORK_STATES)[number];
export type WorkStateSource = (typeof WORK_STATE_SOURCES)[number];
export type WorkStateTone = StatusTone;
export type WorkStateIconRole =
  | "request"
  | "progress"
  | "approval"
  | "success"
  | "warning"
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
  readonly state: WorkState | "UNKNOWN";
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

export type ApprovalOutcome =
  | "pending"
  | "approved"
  | "rejected"
  | "expired"
  | "cancelled"
  | "unknown";

export interface ApprovalStatePresentation {
  readonly outcome: ApprovalOutcome;
  readonly labelKey: string;
  readonly label: string;
  readonly ariaLabel: string;
  readonly tone: WorkStateTone;
  readonly iconRole: WorkStateIconRole;
  readonly terminal: boolean | null;
  readonly work: WorkStatePresentation;
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
    IDLE: definition("ux.work_state.idle", "neutral", "request", false),
    ACCEPTING: definition(
      "ux.work_state.accepting", "neutral", "request", false,
      "review_request", "action.review_request",
    ),
    PLANNING: definition(
      "ux.work_state.planning", "info", "progress", false,
      "view_progress", "action.view_progress",
    ),
    RUNNING: definition(
      "ux.work_state.running", "info", "progress", false,
      "view_progress", "action.view_progress",
    ),
    WAITING_APPROVAL: definition(
      "ux.work_state.waiting_approval", "warning", "approval", false,
      "review_approval", "action.review_approval",
    ),
    RESUMING: definition(
      "ux.work_state.resuming", "info", "progress", false,
      "view_progress", "action.view_progress",
    ),
    VERIFYING: definition(
      "ux.work_state.verifying", "info", "progress", false,
      "view_progress", "action.view_progress",
    ),
    SUCCEEDED: definition(
      "ux.work_state.succeeded", "success", "success", true,
      "view_result", "action.view_result",
    ),
    PARTIAL: definition(
      "ux.work_state.partial", "warning", "warning", true,
      "view_result", "action.view_result",
    ),
    FAILED: definition(
      "ux.work_state.failed", "danger", "error", true,
      "retry", "action.retry",
    ),
    CANCELLED: definition(
      "ux.work_state.cancelled", "neutral", "cancelled", true,
    ),
  });

const WORK_STATE_SET: ReadonlySet<string> = new Set(WORK_STATES);

const COMPATIBILITY_ALIASES: Readonly<Record<string, WorkState>> = Object.freeze({
  REQUESTED: "ACCEPTING",
  IN_PROGRESS: "RUNNING",
  COMPLETED: "SUCCEEDED",
});

const SOURCE_STATE_MAPS: Readonly<
  Record<WorkStateSource, Readonly<Record<string, WorkState>>>
> = Object.freeze({
  AgentExecution: Object.freeze({
    CREATED: "IDLE",
    QUEUED: "ACCEPTING",
    ACCEPTED: "ACCEPTING",
    COMPILED: "PLANNING",
    PLANNING: "PLANNING",
    DISPATCHED: "RUNNING",
    RUNNING: "RUNNING",
    WAITING_APPROVAL: "WAITING_APPROVAL",
    WAITING_FOR_APPROVAL: "WAITING_APPROVAL",
    RESUMING: "RESUMING",
    VERIFYING: "VERIFYING",
    RESULT_VERIFY: "VERIFYING",
    SUCCEEDED: "SUCCEEDED",
    PARTIAL: "PARTIAL",
    FAILED: "FAILED",
    DEAD_LETTER: "FAILED",
    CANCELLED: "CANCELLED",
  }),
  GenerationLifecycle: Object.freeze({
    IDLE: "IDLE",
    ADMITTING: "ACCEPTING",
    PENDING: "ACCEPTING",
    QUEUED: "ACCEPTING",
    ACTIVE: "RUNNING",
    RUNNING: "RUNNING",
    COMPLETED: "SUCCEEDED",
    SUCCEEDED: "SUCCEEDED",
    PARTIAL: "PARTIAL",
    FAILED: "FAILED",
    CANCELLED: "CANCELLED",
  }),
  Approval: Object.freeze({
    PENDING: "WAITING_APPROVAL",
    APPROVED: "SUCCEEDED",
    REJECTED: "SUCCEEDED",
    EXPIRED: "CANCELLED",
    CANCELLED: "CANCELLED",
  }),
  ResultDelivery: Object.freeze({
    PENDING: "ACCEPTING",
    QUEUED: "ACCEPTING",
    PUBLISHING: "RUNNING",
    DELIVERING: "RUNNING",
    VERIFYING: "VERIFYING",
    ACKNOWLEDGED: "SUCCEEDED",
    SUCCEEDED: "SUCCEEDED",
    PARTIAL: "PARTIAL",
    FAILED: "FAILED",
    CANCELLED: "CANCELLED",
  }),
  Artifact: Object.freeze({
    DRAFT: "IDLE",
    QUEUED: "ACCEPTING",
    RENDERING: "RUNNING",
    VERIFYING: "VERIFYING",
    READY: "SUCCEEDED",
    SUCCEEDED: "SUCCEEDED",
    PARTIAL: "PARTIAL",
    FAILED: "FAILED",
    CANCELLED: "CANCELLED",
  }),
  OperationState: Object.freeze({
    IDLE: "IDLE",
    RUNNING: "RUNNING",
    SUCCEEDED: "SUCCEEDED",
    FAILED: "FAILED",
    CANCELLED: "CANCELLED",
  }),
});

const APPROVAL_STATE_DEFINITIONS = Object.freeze({
  PENDING: Object.freeze({ workState: "WAITING_APPROVAL", outcome: "pending" }),
  APPROVED: Object.freeze({ workState: "SUCCEEDED", outcome: "approved" }),
  REJECTED: Object.freeze({ workState: "SUCCEEDED", outcome: "rejected" }),
  EXPIRED: Object.freeze({ workState: "CANCELLED", outcome: "expired" }),
  CANCELLED: Object.freeze({ workState: "CANCELLED", outcome: "cancelled" }),
} as const);

export function mapWorkState(
  internalState: unknown,
  locale = DEFAULT_LOCALE,
): WorkStatePresentation {
  const state = normalizeWorkState(internalState);
  if (state === null) return unknownPresentation(locale);

  const stateDefinition = WORK_STATE_DEFINITIONS[state];
  const label = message(stateDefinition.labelKey, { locale });
  return Object.freeze({
    state,
    known: true,
    labelKey: stateDefinition.labelKey,
    label,
    ariaLabel: label,
    tone: stateDefinition.tone,
    iconRole: stateDefinition.iconRole,
    terminal: stateDefinition.terminal,
    defaultAction: presentDefaultAction(stateDefinition.defaultAction, locale),
    technicalDetailRef: null,
  });
}

export function mapSourceWorkState(
  source: unknown,
  internalState: unknown,
  locale = DEFAULT_LOCALE,
): WorkStatePresentation {
  if (typeof source !== "string" || !WORK_STATE_SOURCES.includes(source as WorkStateSource)) {
    return unknownPresentation(locale);
  }
  const candidate = normalizeInternalState(internalState);
  if (candidate === null) return unknownPresentation(locale);
  const mapped = SOURCE_STATE_MAPS[source as WorkStateSource][candidate];
  return mapped ? mapWorkState(mapped, locale) : unknownPresentation(locale);
}

export function isWorkState(value: unknown): value is WorkState {
  return typeof value === "string" && WORK_STATE_SET.has(value);
}

export function mapApprovalState(
  approvalState: unknown,
  locale = DEFAULT_LOCALE,
): ApprovalStatePresentation {
  const candidate = normalizeInternalState(approvalState) ?? "";
  const stateDefinition =
    APPROVAL_STATE_DEFINITIONS[
      candidate as keyof typeof APPROVAL_STATE_DEFINITIONS
    ];
  if (!stateDefinition) {
    const work = mapWorkState(null, locale);
    return Object.freeze({
      outcome: "unknown",
      labelKey: work.labelKey,
      label: work.label,
      ariaLabel: work.ariaLabel,
      tone: work.tone,
      iconRole: work.iconRole,
      terminal: work.terminal,
      work,
    });
  }

  const work = mapWorkState(stateDefinition.workState, locale);
  const labelKey = `ux.approval_state.${stateDefinition.outcome}`;
  const label = message(labelKey, { locale });
  const tone = approvalOutcomeTone(stateDefinition.outcome, work.tone);
  return Object.freeze({
    outcome: stateDefinition.outcome,
    labelKey,
    label,
    ariaLabel: label,
    tone,
    iconRole: approvalOutcomeIcon(stateDefinition.outcome, work.iconRole),
    terminal: work.terminal,
    work,
  });
}

function normalizeWorkState(value: unknown): WorkState | null {
  const candidate = normalizeInternalState(value);
  if (candidate === null) return null;
  if (WORK_STATE_SET.has(candidate)) return candidate as WorkState;
  return COMPATIBILITY_ALIASES[candidate] ?? null;
}

function normalizeInternalState(value: unknown): string | null {
  if (typeof value !== "string" || !value.trim()) return null;
  return value.trim().toUpperCase().replaceAll(/[-\s]+/g, "_");
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
    state: "UNKNOWN",
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

function approvalOutcomeTone(
  outcome: Exclude<ApprovalOutcome, "unknown">,
  fallback: WorkStateTone,
): WorkStateTone {
  if (outcome === "rejected") return "danger";
  if (outcome === "expired") return "warning";
  return fallback;
}

function approvalOutcomeIcon(
  outcome: Exclude<ApprovalOutcome, "unknown">,
  fallback: WorkStateIconRole,
): WorkStateIconRole {
  if (outcome === "rejected") return "error";
  return fallback;
}
