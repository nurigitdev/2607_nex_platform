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
      operations: operations()
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
    assert.equal(diagnostics.registry.clients.upload, "mock");
    assert.equal(diagnostics.auth_boundary.owner_scope_source, "mock-local");
    assert.equal(diagnostics.session_bootstrap.active_client_mode, "mock");
    assert.equal(diagnostics.session_route_guard.guard_status, "mock_preview");
    assert.equal(summary.operation_count, 2);
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
