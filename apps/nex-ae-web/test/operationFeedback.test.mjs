import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_WEB_OPERATION_FEEDBACK_SCHEMA_VERSION,
  OperationFeedbackError,
  buildOperationFeedback,
  buildRetryControl
} from "../src/operationFeedback.js";
import {
  createOperationState,
  markOperationFailed,
  markOperationRunning,
  markOperationSucceeded
} from "../src/operationState.js";

function idleOperation() {
  return createOperationState({
    operationId: "document_detail",
    label: "Document detail",
    status: "READY",
    route: "/api/v1/documents/doc-001"
  });
}

describe("AE Web operation feedback", () => {
  it("builds pending, running, and success feedback without raw details", () => {
    const idle = buildOperationFeedback(idleOperation(), {
      operationLabel: "문서 상세"
    });
    const running = buildOperationFeedback(markOperationRunning(idleOperation()));
    const succeeded = buildOperationFeedback(
      markOperationSucceeded(markOperationRunning(idleOperation()), {
        status: "COMPLETED",
        resultStatus: "READY"
      })
    );

    assert.equal(idle.operation_feedback_schema_version, AE_WEB_OPERATION_FEEDBACK_SCHEMA_VERSION);
    assert.equal(idle.severity, "pending");
    assert.equal(idle.retry.available, false);
    assert.equal(running.severity, "running");
    assert.equal(running.message, "요청을 처리하고 있습니다.");
    assert.equal(succeeded.severity, "success");
    assert.equal(succeeded.status, "COMPLETED");
    assert.equal(succeeded.metadata.rawErrorMessageIncluded, false);
    assert.doesNotMatch(JSON.stringify(succeeded), /service_token|api_key|database_url|provider_url|raw_error|\/data\/nex-platform/);
  });

  it("exposes retry controls only for retryable failed operations", () => {
    const retryable = buildOperationFeedback(
      markOperationFailed(markOperationRunning(idleOperation()), {
        error: {
          status: "NETWORK_ERROR",
          retryable: true
        }
      }),
      {
        operationLabel: "검색 요청",
        retryLabel: "다시 요청"
      }
    );
    const blocked = buildOperationFeedback(
      markOperationFailed(markOperationRunning(idleOperation()), {
        error: {
          status: "PROJECTION_INVALID",
          retryable: false
        }
      })
    );

    assert.equal(retryable.severity, "danger");
    assert.equal(retryable.retry.available, true);
    assert.equal(retryable.retry.enabled, true);
    assert.equal(retryable.retry.label, "다시 요청");
    assert.equal(retryable.retry.aria_label, "검색 요청 다시 요청");
    assert.equal(retryable.retry.retry_reason, "NETWORK_ERROR");
    assert.match(retryable.message, /다시 시도/);
    assert.equal(blocked.retry.available, false);
    assert.match(blocked.message, /설정 또는 입력/);
  });

  it("rejects invalid summaries and falls back to status for retry reasons", () => {
    assert.throws(
      () => buildRetryControl(null),
      error =>
        error instanceof OperationFeedbackError &&
        error.status === "OPERATION_SUMMARY_INVALID"
    );
    const retry = buildRetryControl({
      phase: "failed",
      retryable: true,
      status: "HTTP_503",
      error_status: null
    });
    const disabled = buildRetryControl({
      phase: "running",
      retryable: true,
      status: "RUNNING"
    });

    assert.equal(retry.retry_reason, "HTTP_503");
    assert.equal(disabled.available, false);
    assert.equal(disabled.retry_reason, null);
  });
});
