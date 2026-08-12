import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_WEB_AUTHENTICATED_RUNTIME_SCHEMA_VERSION,
  AuthenticatedRuntimeError,
  buildAuthenticatedRuntimeSummary,
  createAuthenticatedAeWebRuntime
} from "../src/authenticatedRuntime.js";
import {
  createAnonymousSessionState,
  createMockSessionClient,
  normalizeBrowserSessionSnapshot
} from "../src/sessionClient.js";

function activeSession(overrides = {}) {
  return {
    browser_session_schema_version: "oa_browser_session.v1",
    session_id: "session-0235",
    status: "ACTIVE",
    issuer: "nex-oa",
    audience: "nex-ae-api",
    token_use: "user",
    tenant_ref: { type: "oa.tenant", id: "tenant-a" },
    subject_ref: { type: "oa.user", id: "user-a" },
    scopes: ["workspace:use", "documents:upload"],
    roles: ["employee"],
    issued_at: "2026-08-12T00:00:00Z",
    expires_at: "2026-08-12T01:00:00Z",
    metadata: {
      raw_token_included: false,
      service_token_included: false,
      password_included: false,
      browser_payload_owner_authoritative: false,
      claim_owner_authoritative: true
    },
    ...overrides
  };
}

function documents() {
  return [
    {
      documentId: "doc-001",
      filename: "29_mvp_srs.md",
      ownerScope: {
        tenantId: "tenant-a",
        ownerUserId: "user-a"
      },
      processingStatus: "COMPLETED",
      summaryStatus: "READY"
    }
  ];
}

function createFakeFetch() {
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    calls.push({ url, options });
    if (url === "/ae-api/api/v1/auth/session") {
      return jsonResponse(activeSession());
    }
    if (url === "/ae-api/api/v1/documents/doc-001") {
      return jsonResponse({
        projection_schema_version: "ae_document_detail_projection.v1",
        tenant_id: "tenant-a",
        owner_user_id: "user-a",
        document: {
          document_id: "doc-001",
          filename: "29_mvp_srs.md",
          status: {
            processing_status: "SUCCEEDED",
            extraction_status: "SUCCEEDED",
            summary_status: "SUCCEEDED"
          },
          summary: {
            summary_available: false
          }
        },
        cx: {
          source_kind: "ae-facade"
        }
      });
    }
    return jsonResponse({ error_code: "not_found" }, { ok: false, status: 404 });
  };
  fetchImpl.calls = calls;
  return fetchImpl;
}

function jsonResponse(payload, { ok = true, status = 200 } = {}) {
  return {
    ok,
    status,
    async json() {
      return payload;
    }
  };
}

describe("AE Web authenticated runtime composition", () => {
  it("builds a mock authenticated-runtime envelope with anonymous session state", () => {
    const runtime = createAuthenticatedAeWebRuntime({
      runtimeConfig: { client_mode: "mock" },
      documents: documents()
    });
    const summary = buildAuthenticatedRuntimeSummary(runtime);

    assert.equal(
      runtime.authenticated_runtime_schema_version,
      AE_WEB_AUTHENTICATED_RUNTIME_SCHEMA_VERSION
    );
    assert.equal(summary.runtime_config.client_mode, "mock");
    assert.equal(summary.session_state.status, "anonymous");
    assert.equal(summary.session_client.client_mode, "mock");
    assert.equal(summary.auth_boundary.owner_scope_source, "mock-local");
    assert.equal(summary.fetch_mode_allowed, false);
    assert.equal(summary.registry.clients.document_detail, "mock");
    assert.doesNotMatch(
      JSON.stringify(summary),
      /service_token|api_key|database_url|provider_url|\/data\/nex-platform/
    );
  });

  it("allows fetch clients only with authenticated session claims", async () => {
    const fetchImpl = createFakeFetch();
    const runtime = createAuthenticatedAeWebRuntime({
      runtimeConfig: {
        client_mode: "fetch",
        ae_base_url: "/ae-api",
        features: { fetch_clients_enabled: true }
      },
      sessionState: normalizeBrowserSessionSnapshot(activeSession()),
      fetchImpl,
      documents: documents()
    });

    const session = await runtime.sessionClient.getCurrentSession();
    const detail = await runtime.clientRegistry.documentDetailClient.getDocumentDetail("doc-001");
    const summary = buildAuthenticatedRuntimeSummary(runtime);

    assert.equal(summary.fetch_mode_allowed, true);
    assert.equal(summary.session_state.status, "authenticated");
    assert.equal(summary.session_client.client_mode, "fetch");
    assert.equal(summary.registry.clients.document_detail, "fetch");
    assert.equal(session.status, "authenticated");
    assert.equal(detail.documentId, "doc-001");
    assert.deepEqual(
      fetchImpl.calls.map(call => [call.url, call.options.credentials]),
      [
        ["/ae-api/api/v1/auth/session", "same-origin"],
        ["/ae-api/api/v1/documents/doc-001", "same-origin"]
      ]
    );
  });

  it("blocks fetch runtime when browser session claims are not authenticated", () => {
    assert.throws(
      () =>
        createAuthenticatedAeWebRuntime({
          runtimeConfig: {
            client_mode: "fetch",
            features: { fetch_clients_enabled: true }
          },
          sessionState: createAnonymousSessionState()
        }),
      error =>
        error instanceof AuthenticatedRuntimeError &&
        error.status === "AUTHENTICATED_RUNTIME_FETCH_BLOCKED" &&
        error.blockedReasons.includes("browser_session_not_authenticated")
    );
  });

  it("validates session state, custom session client, and runtime summaries", () => {
    const runtime = createAuthenticatedAeWebRuntime({
      runtimeConfig: { client_mode: "mock" },
      sessionState: normalizeBrowserSessionSnapshot(activeSession()),
      sessionClient: createMockSessionClient({ sessionSnapshot: activeSession() })
    });

    assert.equal(buildAuthenticatedRuntimeSummary(runtime).session_client.client_mode, "mock");
    assert.throws(
      () => createAuthenticatedAeWebRuntime({ sessionState: {} }),
      error =>
        error instanceof AuthenticatedRuntimeError &&
        error.status === "AUTHENTICATED_RUNTIME_SESSION_INVALID"
    );
    assert.throws(
      () => buildAuthenticatedRuntimeSummary({}),
      error =>
        error instanceof AuthenticatedRuntimeError &&
        error.status === "AUTHENTICATED_RUNTIME_SUMMARY_INVALID"
    );
  });
});
