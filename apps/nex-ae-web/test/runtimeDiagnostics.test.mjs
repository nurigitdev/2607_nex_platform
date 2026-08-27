import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  createAeWebClients
} from "../src/clientRegistry.js";
import {
  composeAuthenticatedSessionRuntime
} from "../src/sessionBootstrap.js";
import {
  createOperationState,
  markOperationFailed,
  markOperationRunning,
  markOperationSucceeded
} from "../src/operationState.js";
import {
  AE_WEB_RUNTIME_DIAGNOSTICS_SCHEMA_VERSION,
  RuntimeDiagnosticsError,
  buildRuntimeDiagnostics,
  buildRuntimeDiagnosticsSummary
} from "../src/runtimeDiagnostics.js";
import {
  normalizeRuntimeConfig
} from "../src/runtimeConfig.js";
import {
  buildSessionRouteGuard
} from "../src/sessionRouteGuard.js";
import {
  AE_REPAIRED_RESPONSE_REVIEW_PROJECTION_SCHEMA_VERSION,
  buildRepairedResponseReviewSurfaceFromProjection
} from "../src/repairedResponseReviewClient.js";
import {
  buildRepairedResponseReviewReadModel
} from "../src/repairedResponseReviewReadModel.js";
import {
  createRepairedResponseDecisionState
} from "../src/repairedResponseDecisionState.js";

function runtimeConfig({ mode = "mock" } = {}) {
  return normalizeRuntimeConfig({
    client_mode: mode,
    ae_base_url: mode === "fetch" ? "/ae-api" : "",
    features: {
      document_detail_enabled: true,
      upload_submit_enabled: true,
      retrieval_submit_enabled: true,
      fetch_clients_enabled: mode === "fetch"
    }
  });
}

function operations() {
  const documentDetail = markOperationSucceeded(
    markOperationRunning(
      createOperationState({
        operationId: "document_detail",
        status: "READY"
      })
    ),
    {
      status: "COMPLETED"
    }
  );
  const upload = markOperationFailed(
    markOperationRunning(
      createOperationState({
        operationId: "upload_handoff",
        status: "READY_FOR_SUBMIT"
      })
    ),
    {
      error: {
        status: "NETWORK_ERROR",
        retryable: true
      }
    }
  );
  return { documentDetail, upload };
}

function repairedReviewSurface({ status = "READY_FOR_DECISION" } = {}) {
  return {
    ...buildRepairedResponseReviewSurfaceFromProjection({
      projection_schema_version:
        AE_REPAIRED_RESPONSE_REVIEW_PROJECTION_SCHEMA_VERSION,
      projection_status: "READY_FOR_DECISION",
      repaired_response_handoff_id: `handoff-${status.toLowerCase()}`,
      handoff_request_id: `request-${status.toLowerCase()}`,
      owner_scope: {
        tenant_id: "tenant-local",
        workspace_id: "workspace-local",
        owner_user_id: "owner-local"
      },
      conversation_scope: {
        chat_document_id: "chat-doc-local",
        interaction_id: "interaction-001"
      },
      review_card: {
        title: "수정 응답 검토",
        presentation_mode: "side_by_side_review"
      },
      original_response_ref: {
        cx_generation_id: `cx-gen-parent-${status.toLowerCase()}`,
        link: "/api/v1/generations/parent",
        parent_generation_mutated: false
      },
      repaired_response_summary: {
        cx_generation_id: `cx-gen-repair-${status.toLowerCase()}`,
        status: "SUCCEEDED",
        output_hash: "a".repeat(64),
        output_preview: "근거 누락 지점을 보강했습니다.",
        usage: { input_tokens: 1, output_tokens: 1, total_tokens: 2 },
        quality_summary: {
          grounding_required: true,
          retrieval_package_id: "cx-ret-001",
          grounded_response_quality_status: "PASS"
        }
      },
      lineage_summary: {
        remediation_action_id: `remediation-${status.toLowerCase()}`,
        lineage_status: "REPAIRED",
        action_type: "regenerate_answer",
        lineage_type: "repair",
        attempt_no: 1,
        result_ref: { kind: "cx_generation", id: "cx-gen-repair" }
      },
      decision_controls: {
        available_actions: [
          "view_original",
          "view_repaired",
          "accept_repair",
          "keep_original",
          "view_lineage"
        ],
        primary_actions: ["accept_repair", "keep_original"],
        secondary_actions: ["view_original", "view_repaired", "view_lineage"],
        decision_submit_path:
          `/api/v1/chat/interactions/interaction-001/repaired-response-handoffs/handoff-${status.toLowerCase()}/decisions`
      },
      links: {
        handoff: "/api/v1/handoff",
        original_generation: "/api/v1/generations/parent",
        repaired_generation: "/api/v1/generations/repair",
        remediation_execution: "/api/v1/remediation"
      },
      redaction_summary: {
        raw_output_included: false,
        raw_prompt_included: false,
        raw_source_text_included: false,
        evidence_text_included: false,
        provider_detail_included: false,
        storage_path_included: false
      }
    }),
    decisionState:
      status === "READY_FOR_DECISION"
        ? null
        : createRepairedResponseDecisionState({
            status,
            action: status === "FAILED" ? "keep_original" : "accept_repair"
          })
  };
}

describe("AE Web runtime diagnostics", () => {
  it("summarizes mock runtime, registry, and operations safely", () => {
    const bootstrap = composeAuthenticatedSessionRuntime({
      runtimeConfig: runtimeConfig(),
      documents: [
        {
          documentId: "doc-001",
          filename: "29_mvp_srs.md",
          ownerScope: {
            tenantId: "tenant-local",
            ownerUserId: "owner-local"
          }
        }
      ]
    });
    const runtime = bootstrap.runtime;
    const sessionRouteGuard = buildSessionRouteGuard({
      sessionState: runtime.sessionState,
      authBoundary: runtime.authBoundary,
      clientRegistry: runtime.clientRegistry
    });
    const diagnostics = buildRuntimeDiagnostics({
      runtimeConfig: runtime.runtimeConfig,
      sessionState: runtime.sessionState,
      sessionBootstrap: bootstrap,
      sessionRouteGuard,
      authBoundary: runtime.authBoundary,
      clientRegistry: runtime.clientRegistry,
      operations: operations(),
      repairedResponseReviewReadModel: buildRepairedResponseReviewReadModel([
        repairedReviewSurface(),
        repairedReviewSurface({ status: "FAILED" })
      ])
    });
    const summary = buildRuntimeDiagnosticsSummary(diagnostics);

    assert.equal(
      diagnostics.runtime_diagnostics_schema_version,
      AE_WEB_RUNTIME_DIAGNOSTICS_SCHEMA_VERSION
    );
    assert.equal(diagnostics.client_mode, "mock");
    assert.equal(diagnostics.session_state, "anonymous");
    assert.equal(diagnostics.session_bootstrap_phase, "ready");
    assert.equal(diagnostics.route_guard_status, "mock_preview");
    assert.equal(diagnostics.fetch_clients_enabled, false);
    assert.equal(diagnostics.fetch_mode_allowed, false);
    assert.equal(diagnostics.operation_count, 2);
    assert.equal(diagnostics.failed_operation_count, 1);
    assert.equal(diagnostics.retryable_operation_count, 1);
    assert.equal(diagnostics.repaired_response_review_count, 2);
    assert.equal(diagnostics.repaired_response_actionable_count, 2);
    assert.equal(diagnostics.repaired_response_failed_count, 1);
    assert.equal(diagnostics.registry.clients.upload, "mock");
    assert.equal(diagnostics.auth_boundary.owner_scope_source, "mock-local");
    assert.equal(diagnostics.session_bootstrap.active_client_mode, "mock");
    assert.equal(diagnostics.session_route_guard.guard_status, "mock_preview");
    assert.equal(summary.operation_count, 2);
    assert.equal(summary.repaired_response_review_count, 2);
    assert.equal(summary.repaired_response_actionable_count, 2);
    assert.equal(summary.repaired_response_failed_count, 1);
    assert.equal(summary.session_state, "anonymous");
    assert.equal(summary.session_bootstrap_phase, "ready");
    assert.equal(summary.route_guard_status, "mock_preview");
    assert.equal(summary.metadata.liveNetworkUsed, false);
    assert.doesNotMatch(JSON.stringify(diagnostics), /service_token|api_key|database_url|provider_url|raw_prompt|source_text|\/data\/nex-platform/);
  });

  it("summarizes fetch mode without requiring a live network call", () => {
    const diagnostics = buildRuntimeDiagnostics({
      runtimeConfig: runtimeConfig({ mode: "fetch" }),
      clientRegistry: createAeWebClients({
        mode: "fetch",
        baseUrl: "/ae-api",
        fetchImpl: async () => ({ ok: true, json: async () => ({}) })
      }),
      operations: {}
    });

    assert.equal(diagnostics.client_mode, "fetch");
    assert.equal(diagnostics.ae_base_url, "/ae-api");
    assert.equal(diagnostics.fetch_clients_enabled, true);
    assert.equal(diagnostics.operation_count, 0);
    assert.equal(diagnostics.route_guard_status, "unknown");
    assert.equal(diagnostics.metadata.liveNetworkUsed, false);
  });

  it("rejects invalid diagnostics and operation collections", () => {
    assert.throws(
      () => buildRuntimeDiagnosticsSummary({}),
      error =>
        error instanceof RuntimeDiagnosticsError &&
        error.status === "RUNTIME_DIAGNOSTICS_SCHEMA_INVALID"
    );
    assert.throws(
      () =>
        buildRuntimeDiagnostics({
          runtimeConfig: runtimeConfig(),
          clientRegistry: createAeWebClients({ mode: "mock" }),
          operations: []
        }),
      error =>
        error instanceof RuntimeDiagnosticsError &&
        error.status === "RUNTIME_DIAGNOSTICS_OPERATIONS_INVALID"
    );
  });
});
