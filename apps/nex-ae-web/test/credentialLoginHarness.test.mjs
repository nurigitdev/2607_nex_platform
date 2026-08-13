import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_WEB_CREDENTIAL_LOGIN_HARNESS_SCHEMA_VERSION,
  CredentialLoginHarnessError,
  buildCredentialLoginHarnessSummary,
  runCredentialLoginHarness
} from "../src/credentialLoginHarness.js";
import {
  CredentialLoginSurfaceError
} from "../src/credentialLoginSurface.js";
import {
  SessionClientError
} from "../src/sessionClient.js";

function activeSession({ body = {}, overrides = {} } = {}) {
  return {
    browser_session_schema_version: "oa_browser_session.v1",
    session_id: "session-0261",
    status: "ACTIVE",
    issuer: "nex-oa",
    audience: "nex-ae-api",
    token_use: "user",
    tenant_ref: { type: "oa.tenant", id: body.tenant_id || "tenant-oa" },
    subject_ref: { type: "oa.user", id: "user-emp-001" },
    scopes: body.requested_scopes || ["workspace:use"],
    roles: ["employee"],
    issued_at: "2026-08-13T00:00:00Z",
    expires_at: "2026-08-13T01:00:00Z",
    auth_time: "2026-08-13T00:00:00Z",
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

function createFakeCredentialFetch({ loginStatus = 200, activeOverrides = {} } = {}) {
  const rawCalls = [];
  const fetchImpl = async (url, options = {}) => {
    rawCalls.push({ url, options });

    if (url === "/ae-api/api/v1/auth/session" && options.method === "GET") {
      return jsonResponse({ ok: false, status: 401, payload: {} });
    }

    if (url === "/ae-api/api/v1/auth/session/login") {
      const body = JSON.parse(options.body);
      if (loginStatus !== 200) {
        return jsonResponse({
          ok: false,
          status: loginStatus,
          payload: { error_code: "oa.login_failed" }
        });
      }
      return jsonResponse({
        payload: activeSession({ body, overrides: activeOverrides })
      });
    }

    if (url === "/ae-api/api/v1/auth/session/logout") {
      return jsonResponse({
        payload: activeSession({ overrides: { status: "REVOKED" } })
      });
    }

    return jsonResponse({
      ok: false,
      status: 404,
      payload: { error_code: "ae.fake_route_not_found" }
    });
  };
  fetchImpl.rawCalls = rawCalls;
  return fetchImpl;
}

function jsonResponse({ ok = true, status = 200, payload }) {
  return {
    ok,
    status,
    async json() {
      return payload;
    }
  };
}

describe("AE Web credential login browser harness", () => {
  it("runs current, credential login, route guard, and logout through fake fetch", async () => {
    const fetchImpl = createFakeCredentialFetch();

    const result = await runCredentialLoginHarness({
      baseUrl: "/ae-api/",
      fetchImpl,
      tenantId: "tenant-oa",
      employeeId: "EMP-001",
      password: "Nuri1004!",
      requestedScopes: ["workspace:use", "documents:upload"],
      ttlSeconds: 1800
    });
    const summary = buildCredentialLoginHarnessSummary(result);

    assert.equal(
      result.credential_login_harness_schema_version,
      AE_WEB_CREDENTIAL_LOGIN_HARNESS_SCHEMA_VERSION
    );
    assert.equal(result.current_session.status, "anonymous");
    assert.equal(result.authenticated_session.status, "authenticated");
    assert.equal(result.session_bootstrap.phase, "ready");
    assert.equal(result.session_bootstrap.active_client_mode, "fetch");
    assert.equal(result.route_guard.guard_status, "allowed");
    assert.equal(result.route_guard.allowed_route_count, 4);
    assert.equal(result.logout_session.status, "anonymous");
    assert.equal(result.login_request.route, "/api/v1/auth/session/login");
    assert.equal(result.login_request.password_submitted, true);
    assert.equal(result.login_request.raw_password_in_result, false);
    assert.equal(result.metadata.liveNetworkUsed, false);
    assert.equal(summary.fetch_call_count, 3);
    assert.equal(summary.route_guard_status, "allowed");
    assert.deepEqual(
      result.fetch_calls.map(call => ({
        url: call.url,
        method: call.method,
        credentials: call.credentials,
        request_body_included: call.request_body_included
      })),
      [
        {
          url: "/ae-api/api/v1/auth/session",
          method: "GET",
          credentials: "same-origin",
          request_body_included: false
        },
        {
          url: "/ae-api/api/v1/auth/session/login",
          method: "POST",
          credentials: "same-origin",
          request_body_included: true
        },
        {
          url: "/ae-api/api/v1/auth/session/logout",
          method: "POST",
          credentials: "same-origin",
          request_body_included: false
        }
      ]
    );

    const loginBody = JSON.parse(fetchImpl.rawCalls[1].options.body);
    assert.deepEqual(loginBody, {
      tenant_id: "tenant-oa",
      employee_id: "EMP-001",
      password: "Nuri1004!",
      requested_scopes: ["workspace:use", "documents:upload"],
      ttl_seconds: 1800
    });
    assert.doesNotMatch(
      JSON.stringify(result),
      /Nuri1004|password_hash|access_token|service_token|provider_url|\/data\/nex-platform/
    );
  });

  it("requires injected fetch and credential input before browser calls are made", async () => {
    await assert.rejects(
      () =>
        runCredentialLoginHarness({
          tenantId: "tenant-oa",
          employeeId: "EMP-001",
          password: "Nuri1004!"
        }),
      error =>
        error instanceof CredentialLoginHarnessError &&
        error.status === "CREDENTIAL_LOGIN_HARNESS_FETCH_REQUIRED"
    );

    const fetchImpl = createFakeCredentialFetch();
    await assert.rejects(
      () =>
        runCredentialLoginHarness({
          fetchImpl,
          tenantId: "tenant-oa",
          employeeId: "EMP-001"
        }),
      error =>
        error instanceof CredentialLoginSurfaceError &&
        error.status === "CREDENTIAL_LOGIN_PASSWORD_REQUIRED"
    );
    assert.equal(fetchImpl.rawCalls.length, 0);
  });

  it("keeps login failure visible as a retryable session client boundary", async () => {
    await assert.rejects(
      () =>
        runCredentialLoginHarness({
          fetchImpl: createFakeCredentialFetch({ loginStatus: 503 }),
          tenantId: "tenant-oa",
          employeeId: "EMP-001",
          password: "Nuri1004!"
        }),
      error =>
        error instanceof SessionClientError &&
        error.status === "HTTP_503" &&
        error.retryable === true
    );

    await assert.rejects(
      () =>
        runCredentialLoginHarness({
          fetchImpl: createFakeCredentialFetch({ loginStatus: 401 }),
          tenantId: "tenant-oa",
          employeeId: "EMP-001",
          password: "Nuri1004!"
        }),
      error =>
        error instanceof SessionClientError &&
        error.status === "HTTP_401" &&
        error.retryable === false
    );
  });

  it("rejects invalid summaries and raw secret leakage in harness evidence", async () => {
    assert.throws(
      () => buildCredentialLoginHarnessSummary({}),
      error =>
        error instanceof CredentialLoginHarnessError &&
        error.status === "CREDENTIAL_LOGIN_HARNESS_SUMMARY_INVALID"
    );

    await assert.rejects(
      () =>
        runCredentialLoginHarness({
          fetchImpl: createFakeCredentialFetch({
            activeOverrides: {
              subject_ref: { type: "oa.user", id: "Nuri1004!" }
            }
          }),
          tenantId: "tenant-oa",
          employeeId: "EMP-001",
          password: "Nuri1004!"
        }),
      error =>
        error instanceof CredentialLoginHarnessError &&
        error.status === "CREDENTIAL_LOGIN_HARNESS_SECRET_LEAK"
    );
  });
});
