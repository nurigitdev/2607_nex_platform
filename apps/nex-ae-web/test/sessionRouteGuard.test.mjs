import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  auditAuthenticatedRuntimeBoundary
} from "../src/authBoundary.js";
import {
  createAeWebClients
} from "../src/clientRegistry.js";
import {
  AE_WEB_SESSION_ROUTE_GUARD_SCHEMA_VERSION,
  SessionRouteGuardError,
  buildSessionRouteGuard,
  buildSessionRouteGuardSummary,
  ownerScopeFromSessionState
} from "../src/sessionRouteGuard.js";
import {
  createAnonymousSessionState,
  normalizeBrowserSessionSnapshot
} from "../src/sessionClient.js";

function activeSession(overrides = {}) {
  return normalizeBrowserSessionSnapshot({
    browser_session_schema_version: "oa_browser_session.v1",
    session_id: "session-0259",
    status: "ACTIVE",
    issuer: "nex-oa",
    audience: "nex-ae-api",
    token_use: "user",
    tenant_ref: { type: "oa.tenant", id: "tenant-oa" },
    subject_ref: { type: "oa.user", id: "user-oa" },
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
  });
}

describe("AE Web session route guard", () => {
  it("allows protected fetch routes only with authenticated session claims", () => {
    const sessionState = activeSession();
    const routeGuard = buildSessionRouteGuard({
      sessionState,
      authBoundary: auditAuthenticatedRuntimeBoundary({
        clientMode: "fetch",
        fetchClientsEnabled: true,
        sessionState: "authenticated",
        credentialMode: "same-origin",
        ownerScopeSource: "session-claims"
      }),
      clientRegistry: createAeWebClients({
        mode: "fetch",
        baseUrl: "/ae-api",
        fetchImpl: async () => ({ ok: true, json: async () => ({}) })
      })
    });
    const summary = buildSessionRouteGuardSummary(routeGuard);

    assert.equal(
      routeGuard.session_route_guard_schema_version,
      AE_WEB_SESSION_ROUTE_GUARD_SCHEMA_VERSION
    );
    assert.equal(summary.guard_status, "allowed");
    assert.equal(summary.owner_scope_source, "session-claims");
    assert.equal(summary.allowed_route_count, 4);
    assert.deepEqual(routeGuard.owner_scope, {
      tenant_ref: { type: "oa.tenant", id: "tenant-oa" },
      owner_subject_ref: { type: "oa.user", id: "user-oa" }
    });
    assert.deepEqual(ownerScopeFromSessionState(sessionState), {
      tenantId: "tenant-oa",
      ownerUserId: "user-oa",
      uploadedByUserId: "user-oa",
      source: "session-claims"
    });
    assert.doesNotMatch(
      JSON.stringify(routeGuard),
      /service_token|database_url|provider_url|Nuri1004|password_hash/
    );
  });

  it("reports blocked fetch routes for anonymous sessions", () => {
    const routeGuard = buildSessionRouteGuard({
      sessionState: createAnonymousSessionState(),
      authBoundary: auditAuthenticatedRuntimeBoundary({
        clientMode: "fetch",
        fetchClientsEnabled: true,
        sessionState: "anonymous",
        credentialMode: "same-origin",
        ownerScopeSource: "mock-local"
      }),
      clientRegistry: createAeWebClients({ mode: "mock" })
    });
    const summary = buildSessionRouteGuardSummary(routeGuard);

    assert.equal(summary.guard_status, "blocked");
    assert.equal(summary.allowed_route_count, 0);
    assert.deepEqual(summary.blocked_reasons, [
      "browser_session_not_authenticated",
      "owner_scope_not_claim_derived"
    ]);
    assert.equal(ownerScopeFromSessionState(createAnonymousSessionState()), null);
  });

  it("keeps mock mode visible as a preview route guard", () => {
    const routeGuard = buildSessionRouteGuard({
      sessionState: createAnonymousSessionState(),
      authBoundary: auditAuthenticatedRuntimeBoundary({
        clientMode: "mock",
        sessionState: "anonymous"
      }),
      clientRegistry: createAeWebClients({ mode: "mock" })
    });

    assert.equal(buildSessionRouteGuardSummary(routeGuard).guard_status, "mock_preview");
    assert.equal(routeGuard.protected_routes.at(0).client_mode, "session-client");
  });

  it("rejects invalid route guard summaries", () => {
    assert.throws(
      () => buildSessionRouteGuardSummary({}),
      error =>
        error instanceof SessionRouteGuardError &&
        error.status === "SESSION_ROUTE_GUARD_SUMMARY_INVALID"
    );
  });
});
