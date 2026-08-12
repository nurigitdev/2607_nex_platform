import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_WEB_AUTH_BOUNDARY_SCHEMA_VERSION,
  AuthBoundaryError,
  assertBrowserRuntimeSafe,
  auditAuthenticatedRuntimeBoundary,
  buildAuthBoundarySummary
} from "../src/authBoundary.js";

describe("AE Web authenticated runtime boundary", () => {
  it("keeps the default mock runtime anonymous and browser safe", () => {
    const boundary = auditAuthenticatedRuntimeBoundary();
    const summary = buildAuthBoundarySummary(boundary);

    assert.equal(
      boundary.auth_boundary_schema_version,
      AE_WEB_AUTH_BOUNDARY_SCHEMA_VERSION
    );
    assert.equal(boundary.browser_principal.session_state, "anonymous");
    assert.equal(boundary.browser_principal.token_use, "none");
    assert.equal(boundary.owner_scope.source, "mock-local");
    assert.equal(boundary.fetch_mode.requested, false);
    assert.equal(boundary.fetch_mode.allowed, false);
    assert.equal(summary.browser_calls, "nex-ae-api-only");
    assert.deepEqual(summary.metadata, {
      browserCredentialMode: "none",
      serviceTokenIncluded: false,
      providerSecretIncluded: false,
      databaseUrlIncluded: false,
      storagePathIncluded: false,
      rawSourceIncluded: false
    });
    assert.doesNotMatch(
      JSON.stringify(summary),
      /service_token|api_key|database_url|provider_url|storage_path|raw_source/
    );
  });

  it("allows fetch mode only for authenticated same-origin claim-derived scope", () => {
    const boundary = auditAuthenticatedRuntimeBoundary({
      clientMode: "fetch",
      fetchClientsEnabled: true,
      sessionState: "authenticated",
      credentialMode: "same-origin",
      ownerScopeSource: "session-claims",
      runtimeConfig: {
        client_mode: "fetch",
        features: { fetch_clients_enabled: true }
      }
    });

    assert.equal(boundary.browser_principal.token_use, "user");
    assert.equal(boundary.owner_scope.claimAuthoritative, true);
    assert.equal(boundary.owner_scope.browserPayloadAuthoritative, false);
    assert.equal(boundary.fetch_mode.allowed, true);
    assert.deepEqual(boundary.fetch_mode.blocked_reasons, []);
    assert.equal(boundary.backend_boundary.direct_cx_calls_allowed, false);
    assert.equal(boundary.backend_boundary.direct_database_calls_allowed, false);
  });

  it("blocks fetch mode when any authenticated runtime prerequisite is missing", () => {
    const boundary = auditAuthenticatedRuntimeBoundary({
      clientMode: "fetch",
      fetchClientsEnabled: false,
      sessionState: "expired",
      credentialMode: "none",
      ownerScopeSource: "mock-local"
    });

    assert.equal(boundary.fetch_mode.allowed, false);
    assert.deepEqual(boundary.fetch_mode.blocked_reasons, [
      "fetch_clients_feature_disabled",
      "browser_session_not_authenticated",
      "browser_credentials_not_same_origin",
      "owner_scope_not_claim_derived"
    ]);
  });

  it("rejects unsupported enum values and invalid summaries", () => {
    assert.throws(
      () => auditAuthenticatedRuntimeBoundary({ sessionState: "service" }),
      error => error instanceof AuthBoundaryError && error.status === "SESSION_STATE_UNSUPPORTED"
    );
    assert.throws(
      () => auditAuthenticatedRuntimeBoundary({ credentialMode: "bearer-service-token" }),
      error =>
        error instanceof AuthBoundaryError &&
        error.status === "BROWSER_CREDENTIAL_MODE_UNSUPPORTED"
    );
    assert.throws(
      () => auditAuthenticatedRuntimeBoundary({ ownerScopeSource: "browser-payload" }),
      error =>
        error instanceof AuthBoundaryError &&
        error.status === "OWNER_SCOPE_SOURCE_UNSUPPORTED"
    );
    assert.throws(
      () => buildAuthBoundarySummary({}),
      error =>
        error instanceof AuthBoundaryError &&
        error.status === "AUTH_BOUNDARY_SUMMARY_INVALID"
    );
  });

  it("rejects secret-bearing browser runtime fields recursively", () => {
    assertBrowserRuntimeSafe({
      features: [{ fetch_clients_enabled: true }],
      safe: { nested: "value" }
    });

    for (const runtimeConfig of [
      { service_token: "never-in-browser" },
      { nested: { database_url: "postgresql://user:pass@localhost/db" } },
      { nested: [{ provider_url: "http://model.local" }] },
      { raw_source: "private source" },
      { storage_path: "/data/nex-platform/cx/source-files" }
    ]) {
      assert.throws(
        () => auditAuthenticatedRuntimeBoundary({ runtimeConfig }),
        error =>
          error instanceof AuthBoundaryError &&
          error.status === "BROWSER_RUNTIME_SECRET_FIELD"
      );
    }
  });
});
