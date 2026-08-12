import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_WEB_SESSION_BOOTSTRAP_SCHEMA_VERSION,
  SessionBootstrapError,
  bootstrapAuthenticatedSessionRuntime,
  buildSessionBootstrapSummary,
  composeAuthenticatedSessionRuntime
} from "../src/sessionBootstrap.js";
import {
  normalizeBrowserSessionSnapshot
} from "../src/sessionClient.js";

function activeSession(overrides = {}) {
  return {
    browser_session_schema_version: "oa_browser_session.v1",
    session_id: "session-0237",
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
      }
    }
  ];
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

describe("AE Web session bootstrap", () => {
  it("composes a safe mock bootstrap state for the initial shell", () => {
    const bootstrap = composeAuthenticatedSessionRuntime({
      runtimeConfig: { client_mode: "mock" },
      documents: documents()
    });
    const summary = buildSessionBootstrapSummary(bootstrap);

    assert.equal(
      bootstrap.session_bootstrap_schema_version,
      AE_WEB_SESSION_BOOTSTRAP_SCHEMA_VERSION
    );
    assert.equal(summary.phase, "ready");
    assert.equal(summary.requested_client_mode, "mock");
    assert.equal(summary.active_client_mode, "mock");
    assert.equal(summary.session_state.status, "anonymous");
    assert.equal(summary.session_client.client_mode, "mock");
    assert.deepEqual(summary.blocked_reasons, []);
    assert.doesNotMatch(
      JSON.stringify(summary),
      /service_token|api_key|database_url|provider_url|\/data\/nex-platform/
    );
  });

  it("bootstraps authenticated fetch mode after reading the current session", async () => {
    const calls = [];
    const bootstrap = await bootstrapAuthenticatedSessionRuntime({
      runtimeConfig: {
        client_mode: "fetch",
        ae_base_url: "/ae-api",
        features: { fetch_clients_enabled: true }
      },
      documents: documents(),
      fetchImpl: async (url, options) => {
        calls.push({ url, options });
        return jsonResponse(activeSession());
      }
    });
    const summary = buildSessionBootstrapSummary(bootstrap);

    assert.equal(summary.phase, "ready");
    assert.equal(summary.requested_client_mode, "fetch");
    assert.equal(summary.active_client_mode, "fetch");
    assert.equal(summary.session_state.status, "authenticated");
    assert.equal(summary.session_client.client_mode, "fetch");
    assert.equal(calls[0].url, "/ae-api/api/v1/auth/session");
    assert.equal(calls[0].options.credentials, "same-origin");
  });

  it("falls back to mock clients when fetch mode has no authenticated session", async () => {
    const bootstrap = await bootstrapAuthenticatedSessionRuntime({
      runtimeConfig: {
        client_mode: "fetch",
        ae_base_url: "/ae-api",
        features: { fetch_clients_enabled: true }
      },
      documents: documents(),
      fetchImpl: async () => jsonResponse({ error_code: "missing" }, { ok: false, status: 401 })
    });
    const summary = buildSessionBootstrapSummary(bootstrap);

    assert.equal(summary.phase, "blocked");
    assert.equal(summary.requested_client_mode, "fetch");
    assert.equal(summary.active_client_mode, "mock");
    assert.equal(summary.session_state.status, "anonymous");
    assert.deepEqual(summary.blocked_reasons, [
      "browser_session_not_authenticated",
      "owner_scope_not_claim_derived"
    ]);
    assert.equal(bootstrap.runtime.runtimeConfig.clientMode, "fetch");
    assert.equal(bootstrap.runtime.clientRegistry.clientMode, "mock");
    assert.equal(bootstrap.runtime.authBoundary.fetch_mode.requested, true);
  });

  it("records a failed bootstrap when the session read cannot complete", async () => {
    const bootstrap = await bootstrapAuthenticatedSessionRuntime({
      runtimeConfig: {
        client_mode: "fetch",
        ae_base_url: "/ae-api",
        features: { fetch_clients_enabled: true }
      },
      documents: documents(),
      fetchImpl: async () => {
        throw new Error("offline");
      }
    });
    const summary = buildSessionBootstrapSummary(bootstrap);

    assert.equal(summary.phase, "failed");
    assert.equal(summary.session_read_error_status, "NETWORK_ERROR");
    assert.equal(summary.active_client_mode, "mock");
    assert.equal(summary.metadata.sessionReadFailed, true);
  });

  it("supports pre-read authenticated session state and rejects invalid summaries", () => {
    const bootstrap = composeAuthenticatedSessionRuntime({
      runtimeConfig: {
        client_mode: "fetch",
        ae_base_url: "/ae-api",
        features: { fetch_clients_enabled: true }
      },
      sessionState: normalizeBrowserSessionSnapshot(activeSession()),
      documents: documents(),
      fetchImpl: async () => jsonResponse(activeSession())
    });

    assert.equal(buildSessionBootstrapSummary(bootstrap).active_client_mode, "fetch");
    assert.throws(
      () => buildSessionBootstrapSummary({}),
      error =>
        error instanceof SessionBootstrapError &&
        error.status === "SESSION_BOOTSTRAP_SUMMARY_INVALID"
    );
    assert.throws(
      () =>
        buildSessionBootstrapSummary({
          session_bootstrap_schema_version: AE_WEB_SESSION_BOOTSTRAP_SCHEMA_VERSION,
          phase: "weird"
        }),
      error =>
        error instanceof SessionBootstrapError &&
        error.status === "SESSION_BOOTSTRAP_PHASE_UNSUPPORTED"
    );
  });
});
