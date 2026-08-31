import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_ARTIFACT_LIFECYCLE_ACTION_RESULT_SCHEMA_VERSION,
  AE_ARTIFACT_LIFECYCLE_ACTION_SCHEMA_VERSION,
  buildArtifactLifecycleActionSurface
} from "../src/artifactClient.js";
import {
  AE_WEB_ARTIFACT_LIFECYCLE_ACTION_SET_SCHEMA_VERSION,
  AE_WEB_ARTIFACT_LIFECYCLE_ACTION_STATE_SCHEMA_VERSION,
  ArtifactLifecycleActionStateError,
  assertArtifactLifecycleActionStateSafe,
  buildArtifactLifecycleActionFailureState,
  buildArtifactLifecycleActionRunningState,
  buildArtifactLifecycleActionSet,
  buildArtifactLifecycleActionSetSummary,
  buildArtifactLifecycleActionStateSummary,
  buildArtifactLifecycleActionSuccessState,
  createArtifactLifecycleActionContext,
  createArtifactLifecycleActionState,
  findSensitiveArtifactLifecycleActionStateKeys
} from "../src/artifactLifecycleActionState.js";
import { createOperationState } from "../src/operationState.js";

function artifact(overrides = {}) {
  return {
    artifactId: "artifact-0456",
    artifactStatus: "READY",
    displayTitle: "Generated report",
    clientMode: "fetch",
    ...overrides
  };
}

function lifecyclePayload(overrides = {}) {
  const action = {
    artifact_lifecycle_action_schema_version:
      AE_ARTIFACT_LIFECYCLE_ACTION_SCHEMA_VERSION,
    lifecycle_action_id: "lifecycle-action-0456",
    artifact_id: "artifact-0456",
    action: "ARCHIVE",
    previous_status: "READY",
    target_status: "ARCHIVED",
    restore_status: null,
    reason_code: "user_requested",
    comment_hash: null,
    comment_length: 0,
    actor_ref: {
      actor_type: "user",
      actor_id: "user-0456",
      tenant_id: "tenant-0456"
    },
    request_id: "request-0456",
    trace_id: "0".repeat(32),
    idempotency_key: "artifact-lifecycle-0456",
    metadata: {
      physical_delete_requested: false,
      storage_mutation_requested: false,
      raw_comment_included: false
    }
  };
  return {
    artifact_lifecycle_action_result_schema_version:
      AE_ARTIFACT_LIFECYCLE_ACTION_RESULT_SCHEMA_VERSION,
    lifecycle_action: action,
    artifact_id: "artifact-0456",
    artifact_status: "ARCHIVED",
    previous_status: "READY",
    target_status: "ARCHIVED",
    transition_applied: true,
    routes: {
      artifact: "/api/v1/artifacts/artifact-0456",
      collection: "/api/v1/artifacts"
    },
    updated_at: "2026-08-31T00:00:00Z",
    metadata: {
      rendered_payload_included: false,
      storage_location_included: false,
      physical_delete_executed: false
    },
    ...overrides
  };
}

function operation() {
  return createOperationState({
    operationId: "artifact_lifecycle",
    label: "Artifact lifecycle",
    status: "READY",
    clientMode: "fetch",
    route: "/api/v1/artifacts/artifact-0456/lifecycle-actions"
  });
}

describe("AE Web artifact lifecycle action state", () => {
  it("builds status-aware action sets with safe summaries", () => {
    const readySet = buildArtifactLifecycleActionSet(artifact());
    const archivedSet = buildArtifactLifecycleActionSet(
      artifact({ artifactStatus: "ARCHIVED" })
    );
    const renderingSet = buildArtifactLifecycleActionSet(
      artifact({ artifactStatus: "RENDERING" })
    );
    const readySummary = buildArtifactLifecycleActionSetSummary(readySet);

    assert.equal(
      readySet.artifact_lifecycle_action_set_schema_version,
      AE_WEB_ARTIFACT_LIFECYCLE_ACTION_SET_SCHEMA_VERSION
    );
    assert.equal(readySet.primaryAction, "ARCHIVE");
    assert.deepEqual(
      readySet.actions.filter(action => action.enabled).map(action => action.action),
      ["ARCHIVE", "MARK_DELETED"]
    );
    assert.equal(
      readySet.actions.find(action => action.action === "RESTORE").disabledReason,
      "not_archived_or_deleted"
    );
    assert.equal(archivedSet.primaryAction, "RESTORE");
    assert.deepEqual(
      archivedSet.actions.filter(action => action.enabled).map(action => action.action),
      ["RESTORE", "MARK_DELETED"]
    );
    assert.equal(renderingSet.enabledActionCount, 0);
    assert.equal(renderingSet.actions[0].disabledReason, "artifact_rendering");
    assert.equal(readySummary.enabled_action_count, 2);
    assert.equal(readySummary.route_present, true);
    assert.doesNotMatch(
      JSON.stringify({ readySet, readySummary }),
      /storage_ref|database_url|service_token|\/data\/nex-platform/
    );
  });

  it("creates lifecycle contexts and idle/running summaries", () => {
    const actionSet = buildArtifactLifecycleActionSet(artifact());
    const context = createArtifactLifecycleActionContext({
      artifactId: "artifact-0456",
      artifactStatus: "READY",
      action: "archive",
      clientMode: "fetch"
    });
    const idle = createArtifactLifecycleActionState({
      status: "IDLE",
      actionSet,
      clientMode: "fetch"
    });
    const running = buildArtifactLifecycleActionRunningState(operation(), context);
    const idleSummary = buildArtifactLifecycleActionStateSummary(idle);
    const runningSummary = buildArtifactLifecycleActionStateSummary(running);

    assert.equal(
      context.artifact_lifecycle_action_state_schema_version,
      AE_WEB_ARTIFACT_LIFECYCLE_ACTION_STATE_SCHEMA_VERSION
    );
    assert.equal(context.action, "ARCHIVE");
    assert.equal(context.targetStatus, "ARCHIVED");
    assert.equal(context.restoreStatus, null);
    assert.equal(idleSummary.enabled_action_count, 2);
    assert.equal(idleSummary.primary_action, "ARCHIVE");
    assert.equal(running.status, "RUNNING");
    assert.equal(running.operation.phase, "running");
    assert.equal(runningSummary.phase, "running");
    assert.equal(runningSummary.route_present, true);
  });

  it("records success and failure states without raw details", () => {
    const context = createArtifactLifecycleActionContext({
      artifactId: "artifact-0456",
      artifactStatus: "READY",
      action: "ARCHIVE",
      clientMode: "fetch"
    });
    const surface = buildArtifactLifecycleActionSurface(lifecyclePayload(), {
      clientMode: "fetch",
      route: context.route
    });
    const success = buildArtifactLifecycleActionSuccessState(
      operation(),
      surface,
      context
    );
    const error = new Error("hidden database_url detail");
    error.status = "ARTIFACT_LIFECYCLE_TIMEOUT";
    error.retryable = true;
    const failure = buildArtifactLifecycleActionFailureState(
      operation(),
      error,
      context
    );
    const successSummary = buildArtifactLifecycleActionStateSummary(success);
    const failureSummary = buildArtifactLifecycleActionStateSummary(failure);

    assert.equal(success.status, "APPLIED");
    assert.equal(success.operation.phase, "succeeded");
    assert.equal(success.operation.resultStatus, "ARCHIVED");
    assert.equal(success.resultSummary.artifact_status, "ARCHIVED");
    assert.equal(successSummary.transition_applied, true);
    assert.equal(failure.status, "UNAVAILABLE");
    assert.equal(failure.operation.phase, "failed");
    assert.equal(failureSummary.error_status, "ARTIFACT_LIFECYCLE_TIMEOUT");
    assert.equal(failureSummary.retryable, true);
    assert.doesNotMatch(JSON.stringify(failure), /hidden|database_url/);
  });

  it("supports restore contexts for archived and deleted artifacts", () => {
    const archivedContext = createArtifactLifecycleActionContext({
      artifactId: "artifact-0456",
      artifactStatus: "ARCHIVED",
      action: "RESTORE",
      restoreStatus: "failed"
    });
    const deletedSet = buildArtifactLifecycleActionSet(
      artifact({ artifactStatus: "DELETED" })
    );

    assert.equal(archivedContext.targetStatus, "FAILED");
    assert.equal(archivedContext.restoreStatus, "FAILED");
    assert.deepEqual(
      deletedSet.actions.filter(action => action.enabled).map(action => action.action),
      ["RESTORE"]
    );
    assert.equal(deletedSet.primaryAction, "RESTORE");
  });

  it("rejects invalid transitions, schemas, and sensitive material", () => {
    assert.throws(
      () =>
        createArtifactLifecycleActionContext({
          artifactId: "artifact-0456",
          artifactStatus: "READY",
          action: "RESTORE"
        }),
      error =>
        error instanceof ArtifactLifecycleActionStateError &&
        error.status === "ARTIFACT_LIFECYCLE_ACTION_UNAVAILABLE"
    );
    assert.throws(
      () =>
        createArtifactLifecycleActionContext({
          artifactId: "artifact-0456",
          artifactStatus: "ARCHIVED",
          action: "ARCHIVE"
        }),
      error =>
        error instanceof ArtifactLifecycleActionStateError &&
        error.status === "ARTIFACT_LIFECYCLE_ACTION_UNAVAILABLE"
    );
    assert.throws(
      () =>
        createArtifactLifecycleActionContext({
          artifactId: "artifact-0456",
          artifactStatus: "READY",
          action: "ARCHIVE",
          restoreStatus: "READY"
        }),
      error =>
        error instanceof ArtifactLifecycleActionStateError &&
        error.status === "ARTIFACT_LIFECYCLE_RESTORE_STATUS_UNSUPPORTED"
    );
    assert.throws(
      () => buildArtifactLifecycleActionSet(artifact({ artifactStatus: "UNKNOWN" })),
      error =>
        error instanceof ArtifactLifecycleActionStateError &&
        error.status === "ARTIFACT_LIFECYCLE_ARTIFACT_STATUS_UNSUPPORTED"
    );
    assert.throws(
      () => buildArtifactLifecycleActionSetSummary({}),
      error =>
        error instanceof ArtifactLifecycleActionStateError &&
        error.status === "ARTIFACT_LIFECYCLE_ACTION_SET_INVALID"
    );
    assert.throws(
      () => buildArtifactLifecycleActionStateSummary({}),
      error =>
        error instanceof ArtifactLifecycleActionStateError &&
        error.status === "ARTIFACT_LIFECYCLE_ACTION_STATE_SCHEMA_INVALID"
    );
    assert.throws(
      () =>
        buildArtifactLifecycleActionSuccessState(
          operation(),
          buildArtifactLifecycleActionSurface(
            lifecyclePayload({
              lifecycle_action: {
                ...lifecyclePayload().lifecycle_action,
                artifact_id: "artifact-other"
              },
              artifact_id: "artifact-other",
              routes: {
                artifact: "/api/v1/artifacts/artifact-other",
                collection: "/api/v1/artifacts"
              }
            })
          ),
          createArtifactLifecycleActionContext({
            artifactId: "artifact-0456",
            artifactStatus: "READY",
            action: "ARCHIVE"
          })
        ),
      error =>
        error instanceof ArtifactLifecycleActionStateError &&
        error.status === "ARTIFACT_LIFECYCLE_RESULT_CONTEXT_MISMATCH"
    );
    assert.deepEqual(
      findSensitiveArtifactLifecycleActionStateKeys({
        nested: { raw_comment: "private" }
      }),
      ["nested.raw_comment"]
    );
    assert.throws(
      () =>
        assertArtifactLifecycleActionStateSafe({
          route: "postgresql+psycopg://nex_ae_user:nuri1004@127.0.0.1:5432/nex"
        }),
      error =>
        error instanceof ArtifactLifecycleActionStateError &&
        error.status === "ARTIFACT_LIFECYCLE_ACTION_STATE_SENSITIVE_VALUE"
    );
  });
});
