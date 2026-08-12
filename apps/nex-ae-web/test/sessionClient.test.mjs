import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_WEB_SESSION_CLIENT_SCHEMA_VERSION,
  AE_WEB_SESSION_STATE_SCHEMA_VERSION,
  SessionClientError,
  assertSessionPayloadSafe,
  buildSessionClientSummary,
  buildSessionStateSummary,
  createAnonymousSessionState,
  createExpiredSessionState,
  createFetchSessionClient,
  createMockSessionClient,
  normalizeBrowserSessionSnapshot
} from "../src/sessionClient.js";

function activeSession(overrides = {}) {
  return {
    browser_session_schema_version: "oa_browser_session.v1",
    session_id: "session-0234",
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
    auth_time: "2026-08-12T00:00:00Z",
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

describe("AE Web session client", () => {
  it("builds anonymous and expired session summaries without credential material", () => {
    const anonymous = createAnonymousSessionState();
    const expired = createExpiredSessionState({ sessionId: "session-old" });

    assert.equal(anonymous.session_state_schema_version, AE_WEB_SESSION_STATE_SCHEMA_VERSION);
    assert.equal(anonymous.status, "anonymous");
    assert.equal(expired.status, "expired");
    assert.equal(expired.sessionId, "session-old");
    assert.deepEqual(buildSessionStateSummary(anonymous).metadata, {
      rawTokenIncluded: false,
      serviceTokenIncluded: false,
      passwordIncluded: false,
      browserPayloadOwnerAuthoritative: false,
      claimOwnerAuthoritative: true
    });
    assert.doesNotMatch(JSON.stringify(buildSessionStateSummary(anonymous)), /nex-mock|secret|raw_value/);
  });

  it("normalizes an active OA browser session snapshot into safe web state", () => {
    const state = normalizeBrowserSessionSnapshot(activeSession());
    const summary = buildSessionStateSummary(state);

    assert.equal(state.status, "authenticated");
    assert.deepEqual(state.tenantRef, { type: "oa.tenant", id: "tenant-a" });
    assert.deepEqual(state.subjectRef, { type: "oa.user", id: "user-a" });
    assert.deepEqual(state.scopes, ["workspace:use", "documents:upload"]);
    assert.equal(summary.scope_count, 2);
    assert.equal(summary.role_count, 1);
    assert.equal(summary.session_id_present, true);
  });

  it("normalizes expired and revoked snapshots to non-authenticated states", () => {
    assert.equal(
      normalizeBrowserSessionSnapshot(activeSession({ status: "EXPIRED" })).status,
      "expired"
    );
    assert.equal(
      normalizeBrowserSessionSnapshot(activeSession({ status: "REVOKED" })).reason,
      "revoked"
    );
  });

  it("rejects unsafe or malformed session snapshots", () => {
    for (const snapshot of [
      null,
      activeSession({ browser_session_schema_version: "old" }),
      activeSession({ token_use: "service" }),
      activeSession({ audience: "nex-cx" }),
      activeSession({ status: "BROKEN" }),
      activeSession({ tenant_ref: { type: "wrong", id: "tenant-a" } }),
      activeSession({ subject_ref: { type: "wrong", id: "user-a" } }),
      activeSession({ scopes: "workspace:use" }),
      activeSession({ roles: "employee" }),
      activeSession({
        metadata: {
          raw_token_included: true,
          service_token_included: false,
          password_included: false,
          browser_payload_owner_authoritative: false,
          claim_owner_authoritative: true
        }
      })
    ]) {
      assert.throws(
        () => normalizeBrowserSessionSnapshot(snapshot),
        error => error instanceof SessionClientError
      );
    }
  });

  it("creates mock session client adapters for current session, login, and logout", async () => {
    const client = createMockSessionClient({ sessionSnapshot: activeSession() });
    const summary = buildSessionClientSummary(client);

    assert.equal(client.session_client_schema_version, AE_WEB_SESSION_CLIENT_SCHEMA_VERSION);
    assert.equal(summary.client_mode, "mock");
    assert.equal((await client.getCurrentSession()).status, "authenticated");
    assert.equal((await client.login()).status, "authenticated");
    assert.equal((await client.logout()).status, "anonymous");

    await assert.rejects(
      () => createMockSessionClient().login(),
      error => error instanceof SessionClientError && error.status === "MOCK_LOGIN_UNAVAILABLE"
    );
  });

  it("creates fetch session client adapters with same-origin credentials", async () => {
    const calls = [];
    const client = createFetchSessionClient({
      baseUrl: "/ae-api/",
      fetchImpl: async (url, options) => {
        calls.push({ url, options });
        return {
          ok: true,
          status: 200,
          async json() {
            return activeSession();
          }
        };
      }
    });

    assert.equal((await client.getCurrentSession()).status, "authenticated");
    assert.equal((await client.login({ login_hint: "user-a" })).status, "authenticated");
    await client.logout();

    assert.equal(calls[0].url, "/ae-api/api/v1/auth/session");
    assert.equal(calls[0].options.credentials, "same-origin");
    assert.equal(calls[1].options.method, "POST");
    assert.equal(calls[2].url, "/ae-api/api/v1/auth/session/logout");
  });

  it("maps fetch errors and rejects unsafe login hints", async () => {
    await assert.rejects(
      () => createFetchSessionClient({ fetchImpl: null }).getCurrentSession(),
      error => error instanceof SessionClientError && error.status === "FETCH_UNAVAILABLE"
    );
    await assert.rejects(
      () =>
        createFetchSessionClient({
          fetchImpl: async () => {
            throw new Error("offline");
          }
        }).getCurrentSession(),
      error => error instanceof SessionClientError && error.status === "NETWORK_ERROR"
    );
    await assert.rejects(
      () =>
        createFetchSessionClient({
          fetchImpl: async () => ({ ok: false, status: 503 })
        }).getCurrentSession(),
      error => error instanceof SessionClientError && error.status === "HTTP_503"
    );
    await assert.rejects(
      () => createFetchSessionClient().login({ access_token: "raw" }),
      error => error instanceof SessionClientError && error.status === "SESSION_SECRET_FIELD"
    );
  });

  it("rejects invalid summaries, base URLs, and forbidden session fields", () => {
    assert.throws(
      () => buildSessionStateSummary({}),
      error => error instanceof SessionClientError && error.status === "SESSION_STATE_SUMMARY_INVALID"
    );
    assert.throws(
      () => buildSessionClientSummary({}),
      error => error instanceof SessionClientError && error.status === "SESSION_CLIENT_SUMMARY_INVALID"
    );
    assert.throws(
      () => createFetchSessionClient({ baseUrl: 3 }),
      error => error instanceof SessionClientError && error.status === "BASE_URL_INVALID"
    );

    assertSessionPayloadSafe({ safe: [{ nested: "ok" }] });
    for (const payload of [
      { access_token: "raw" },
      { nested: { service_token: "raw" } },
      { nested: [{ database_url: "postgresql://user:pass@localhost/db" }] },
      { password: "raw" }
    ]) {
      assert.throws(
        () => assertSessionPayloadSafe(payload),
        error => error instanceof SessionClientError && error.status === "SESSION_SECRET_FIELD"
      );
    }
  });
});
