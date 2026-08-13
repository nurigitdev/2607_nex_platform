#!/usr/bin/env node
import { pathToFileURL } from "node:url";

import {
  AE_WEB_CREDENTIAL_LOGIN_HARNESS_SCHEMA_VERSION,
  buildCredentialLoginHarnessSummary,
  runCredentialLoginHarness
} from "../src/credentialLoginHarness.js";

export const AE_WEB_CREDENTIAL_LOGIN_BROWSER_HARNESS_SMOKE_SCHEMA_VERSION =
  "ae_web_credential_login_browser_harness_smoke.v1";

const HARNESS_LOGIN_SECRET = "slice-0263-login-secret";
const HARNESS_INPUT = {
  baseUrl: "/ae-api",
  tenantId: "tenant-slice-0263",
  employeeId: "EMP-0263",
  password: HARNESS_LOGIN_SECRET,
  requestedScopes: ["workspace:use", "documents:upload"],
  ttlSeconds: 1800
};

export async function runCredentialLoginBrowserHarnessSmoke() {
  const result = await runCredentialLoginHarness({
    ...HARNESS_INPUT,
    fetchImpl: createFakeCredentialFetch()
  });
  const summary = buildCredentialLoginHarnessSummary(result);
  const checks = buildChecks(result);
  const evidence = {
    smoke_schema_version:
      AE_WEB_CREDENTIAL_LOGIN_BROWSER_HARNESS_SMOKE_SCHEMA_VERSION,
    evidence_generated_at: new Date().toISOString(),
    status: Object.values(checks).every(Boolean) ? "PASS" : "FAIL",
    runner: {
      mode: "deterministic_fake_fetch",
      boundary_slice: "Slice 0262",
      live_network_used: false,
      postgresql_used: false
    },
    harness: {
      schema_version: AE_WEB_CREDENTIAL_LOGIN_HARNESS_SCHEMA_VERSION,
      summary,
      credential_surface: result.credential_surface,
      login_request: result.login_request,
      fetch_calls: result.fetch_calls
    },
    checks,
    redaction: {
      rawPasswordInEvidence: false,
      rawTokenInEvidence: false,
      cookieMaterialInEvidence: false,
      serviceCredentialInEvidence: false,
      databaseEndpointInEvidence: false,
      providerEndpointInEvidence: false
    }
  };
  assertBrowserHarnessSmokeEvidenceRedacted(evidence, {
    rawPassword: HARNESS_LOGIN_SECRET
  });
  return evidence;
}

export function formatSummary(evidence) {
  if (evidence.status === "PASS") {
    return (
      "ae_web_credential_login_browser_harness_smoke=pass " +
      `mode=${evidence.runner.mode} ` +
      `route_guard=${evidence.harness.summary.route_guard_status} ` +
      `fetch_calls=${evidence.harness.summary.fetch_call_count}`
    );
  }
  return "ae_web_credential_login_browser_harness_smoke=fail";
}

export function assertBrowserHarnessSmokeEvidenceRedacted(
  evidence,
  { rawPassword } = {}
) {
  const serialized = JSON.stringify(evidence);
  if (rawPassword && serialized.includes(rawPassword)) {
    throw new Error("credential login browser harness smoke leaked raw password");
  }
  for (const fragment of [
    "access_" + "token",
    "password_" + "hash",
    `database_${"url"}`,
    `provider_${"url"}`,
    `service_${"token"}`,
    "/data/" + "nex-platform"
  ]) {
    if (serialized.includes(fragment)) {
      throw new Error("credential login browser harness smoke leaked server material");
    }
  }
}

export async function main(argv = process.argv.slice(2), output = console.log) {
  const summary = argv.includes("--summary");
  try {
    const evidence = await runCredentialLoginBrowserHarnessSmoke();
    output(
      summary
        ? formatSummary(evidence)
        : JSON.stringify(evidence, null, 2)
    );
    return evidence.status === "PASS" ? 0 : 1;
  } catch (error) {
    output(
      "ae_web_credential_login_browser_harness_smoke=fail " +
      `error=${error?.constructor?.name || "Error"}`
    );
    return 1;
  }
}

function buildChecks(result) {
  const serialized = JSON.stringify(result);
  return {
    current_session_anonymous: result.current_session.status === "anonymous",
    authenticated_session_active:
      result.authenticated_session.status === "authenticated",
    runtime_fetch_ready: result.session_bootstrap.active_client_mode === "fetch",
    route_guard_allowed: result.route_guard.guard_status === "allowed",
    logout_returns_anonymous: result.logout_session.status === "anonymous",
    fetch_call_sequence_matches_auth_routes: authRouteSequence(result.fetch_calls),
    login_body_redacted: !serialized.includes(HARNESS_LOGIN_SECRET),
    live_network_not_used: true
  };
}

function authRouteSequence(fetchCalls) {
  return (
    Array.isArray(fetchCalls) &&
    fetchCalls.map(call => `${call.method} ${call.url}`).join("|") ===
      [
        "GET /ae-api/api/v1/auth/session",
        "POST /ae-api/api/v1/auth/session/login",
        "POST /ae-api/api/v1/auth/session/logout"
      ].join("|")
  );
}

function createFakeCredentialFetch() {
  return async (url, options = {}) => {
    if (url === "/ae-api/api/v1/auth/session" && options.method === "GET") {
      return jsonResponse({ ok: false, status: 401, payload: {} });
    }
    if (url === "/ae-api/api/v1/auth/session/login") {
      const body = JSON.parse(options.body);
      return jsonResponse({
        payload: activeSession({ body })
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
}

function activeSession({ body = {}, overrides = {} } = {}) {
  return {
    browser_session_schema_version: "oa_browser_session.v1",
    session_id: "session-0263",
    status: "ACTIVE",
    issuer: "nex-oa",
    audience: "nex-ae-api",
    token_use: "user",
    tenant_ref: { type: "oa.tenant", id: body.tenant_id || "tenant-slice-0263" },
    subject_ref: { type: "oa.user", id: "user-slice-0263" },
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

function jsonResponse({ ok = true, status = 200, payload }) {
  return {
    ok,
    status,
    async json() {
      return payload;
    }
  };
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  main().then(code => {
    process.exitCode = code;
  });
}
