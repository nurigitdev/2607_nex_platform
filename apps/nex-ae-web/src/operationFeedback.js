import {
  buildOperationStateSummary
} from "./operationState.js";

export const AE_WEB_OPERATION_FEEDBACK_SCHEMA_VERSION =
  "ae_web_operation_feedback.v1";

export class OperationFeedbackError extends Error {
  constructor(message, { status = "OPERATION_FEEDBACK_INVALID" } = {}) {
    super(message);
    this.name = "OperationFeedbackError";
    this.status = status;
  }
}

export function buildOperationFeedback(
  operationState,
  {
    operationLabel = "operation",
    idleMessage = "요청 준비가 완료되었습니다.",
    runningMessage = "요청을 처리하고 있습니다.",
    succeededMessage = "요청이 완료되었습니다.",
    failedMessage = "요청을 완료하지 못했습니다.",
    retryLabel = "재시도"
  } = {}
) {
  const summary = buildOperationStateSummary(operationState);
  const phase = summary.phase;
  const severity = severityForPhase(phase);
  const message = messageForPhase(phase, {
    idleMessage,
    runningMessage,
    succeededMessage,
    failedMessage,
    retryable: summary.retryable
  });

  return {
    operation_feedback_schema_version: AE_WEB_OPERATION_FEEDBACK_SCHEMA_VERSION,
    operation_id: summary.operation_id,
    phase,
    status: summary.status,
    severity,
    message,
    retry: buildRetryControl(summary, {
      operationLabel,
      retryLabel
    }),
    metadata: {
      rawErrorMessageIncluded: false,
      rawPromptRendered: false,
      rawSourceIncluded: false,
      providerEndpointIncluded: false,
      databaseEndpointIncluded: false,
      storageLocationIncluded: false
    }
  };
}

export function buildRetryControl(
  operationSummary,
  { operationLabel = "operation", retryLabel = "재시도" } = {}
) {
  if (!operationSummary || typeof operationSummary !== "object") {
    throw new OperationFeedbackError("Operation summary is invalid.", {
      status: "OPERATION_SUMMARY_INVALID"
    });
  }
  const available = operationSummary.phase === "failed" && operationSummary.retryable;
  return {
    available,
    enabled: available,
    label: retryLabel,
    aria_label: `${operationLabel} ${retryLabel}`,
    retry_reason: available
      ? operationSummary.error_status || operationSummary.status
      : null
  };
}

function severityForPhase(phase) {
  if (phase === "running") return "running";
  if (phase === "succeeded") return "success";
  if (phase === "failed") return "danger";
  if (phase === "idle") return "pending";
  throw new OperationFeedbackError("Operation phase is unsupported.", {
    status: "OPERATION_FEEDBACK_PHASE_UNSUPPORTED"
  });
}

function messageForPhase(
  phase,
  { idleMessage, runningMessage, succeededMessage, failedMessage, retryable }
) {
  if (phase === "idle") return idleMessage;
  if (phase === "running") return runningMessage;
  if (phase === "succeeded") return succeededMessage;
  if (phase === "failed" && retryable) {
    return `${failedMessage} 다시 시도할 수 있습니다.`;
  }
  if (phase === "failed") return `${failedMessage} 설정 또는 입력을 확인하세요.`;
  throw new OperationFeedbackError("Operation phase is unsupported.", {
    status: "OPERATION_FEEDBACK_PHASE_UNSUPPORTED"
  });
}
