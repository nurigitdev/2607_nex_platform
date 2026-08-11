import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_WEB_OPERATION_STATE_SCHEMA_VERSION,
  OperationStateError,
  buildOperationStateSummary,
  createOperationState,
  markOperationFailed,
  markOperationRunning,
  markOperationSucceeded
} from "../src/operationState.js";

describe("AE Web operation state model", () => {
  it("creates an idle operation and exposes a safe summary", () => {
    const state = createOperationState({
      operationId: "document_detail",
      label: "Document detail",
      status: "READY",
      route: "/api/v1/documents/doc-001",
      metadata: {
        providerEndpointIncluded: true,
        ignoredUnsafeField: true
      }
    });
    const summary = buildOperationStateSummary(state);

    assert.equal(state.operation_state_schema_version, AE_WEB_OPERATION_STATE_SCHEMA_VERSION);
    assert.equal(summary.operation_id, "document_detail");
    assert.equal(summary.phase, "idle");
    assert.equal(summary.status, "READY");
    assert.equal(summary.retryable, false);
    assert.equal(summary.attempt, 0);
    assert.equal(summary.route, "/api/v1/documents/doc-001");
    assert.equal(summary.metadata.providerEndpointIncluded, false);
    assert.equal(summary.metadata.browserServiceTokenIncluded, false);
    assert.equal("ignoredUnsafeField" in summary.metadata, false);
    assert.doesNotMatch(JSON.stringify(summary), /service_token|api_key|database_url|provider_url|\/data\/nex-platform/);
  });

  it("moves operations through running and succeeded states", () => {
    const idle = createOperationState({
      operationId: "retrieval_context",
      status: "READY_FOR_PROMPT",
      clientMode: "fetch",
      route: "/api/v1/retrieval/contexts"
    });
    const running = markOperationRunning(idle, {
      startedAt: "2026-08-12T00:00:00Z"
    });
    const succeeded = markOperationSucceeded(running, {
      status: "COMPLETED",
      resultStatus: "READY",
      finishedAt: "2026-08-12T00:00:01Z"
    });

    assert.equal(running.phase, "running");
    assert.equal(running.status, "RUNNING");
    assert.equal(running.attempt, 1);
    assert.equal(running.retryable, false);
    assert.equal(succeeded.phase, "succeeded");
    assert.equal(succeeded.status, "COMPLETED");
    assert.equal(succeeded.resultStatus, "READY");
    assert.equal(succeeded.errorStatus, null);
    assert.equal(succeeded.attempt, 1);
  });

  it("normalizes failed states with retryable error metadata", () => {
    const idle = createOperationState({
      operationId: "upload_handoff",
      status: "READY_FOR_SUBMIT"
    });
    const running = markOperationRunning(idle, { attempt: 3 });
    const failed = markOperationFailed(running, {
      error: {
        status: "NETWORK_ERROR",
        retryable: true
      },
      finishedAt: "2026-08-12T00:00:02Z"
    });
    const summary = buildOperationStateSummary(failed);

    assert.equal(failed.phase, "failed");
    assert.equal(failed.status, "UNAVAILABLE");
    assert.equal(failed.errorStatus, "NETWORK_ERROR");
    assert.equal(failed.retryable, true);
    assert.equal(failed.resultStatus, null);
    assert.equal(summary.error_status, "NETWORK_ERROR");
    assert.equal(summary.retryable, true);
  });

  it("rejects invalid operation states and unsupported phases", () => {
    assert.throws(
      () => createOperationState({ operationId: "" }),
      error => error instanceof OperationStateError && error.status === "OPERATION_ID_INVALID"
    );
    assert.throws(
      () => createOperationState({ operationId: "upload", phase: "queued" }),
      error =>
        error instanceof OperationStateError &&
        error.status === "OPERATION_PHASE_UNSUPPORTED"
    );
    assert.throws(
      () => createOperationState({ operationId: "upload", attempt: -1 }),
      error =>
        error instanceof OperationStateError &&
        error.status === "OPERATION_ATTEMPT_INVALID"
    );
    assert.throws(
      () => buildOperationStateSummary({}),
      error =>
        error instanceof OperationStateError &&
        error.status === "OPERATION_STATE_SCHEMA_INVALID"
    );
  });
});
