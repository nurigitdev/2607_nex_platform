import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_WEB_CREDENTIAL_LOGIN_SURFACE_SCHEMA_VERSION,
  CredentialLoginSurfaceError,
  assertCredentialLoginRequestShape,
  buildCredentialLoginRequest,
  buildCredentialLoginRequestFromForm,
  buildCredentialLoginSurfaceSummary,
  createCredentialLoginSurfaceState
} from "../src/credentialLoginSurface.js";

describe("AE Web credential-login surface", () => {
  it("builds employee credential login requests while keeping summaries safe", () => {
    const request = buildCredentialLoginRequest({
      tenantId: " tenant-oa ",
      employeeId: " EMP-001 ",
      password: "Nuri1004!",
      requestedScopes: ["workspace:use", "documents:upload"],
      ttlSeconds: 1800
    });
    const state = createCredentialLoginSurfaceState({
      tenantId: request.tenant_id,
      employeeId: request.employee_id,
      requestedScopes: request.requested_scopes,
      ttlSeconds: request.ttl_seconds,
      status: "AUTHENTICATED",
      reason: "login_succeeded"
    });
    const summary = buildCredentialLoginSurfaceSummary(state);

    assert.equal(
      state.credential_login_surface_schema_version,
      AE_WEB_CREDENTIAL_LOGIN_SURFACE_SCHEMA_VERSION
    );
    assert.deepEqual(request, {
      tenant_id: "tenant-oa",
      employee_id: "EMP-001",
      password: "Nuri1004!",
      requested_scopes: ["workspace:use", "documents:upload"],
      ttl_seconds: 1800
    });
    assert.equal(summary.status, "AUTHENTICATED");
    assert.equal(summary.employee_id_present, true);
    assert.equal(summary.requested_scope_count, 2);
    assert.deepEqual(summary.metadata, {
      rawPasswordStored: false,
      passwordRendered: false,
      passwordIncludedInSummary: false,
      serviceTokenIncluded: false,
      databaseEndpointIncluded: false,
      providerEndpointIncluded: false
    });
    assert.doesNotMatch(JSON.stringify({ state, summary }), /Nuri1004|password_hash|service_token|database_url|provider_url/);
  });

  it("accepts loginIdentifier and DOM-like form inputs", () => {
    assert.equal(
      buildCredentialLoginRequest({
        tenantId: "tenant-oa",
        loginIdentifier: "EMP-002",
        password: "Nuri1004!"
      }).employee_id,
      "EMP-002"
    );
    assert.deepEqual(
      buildCredentialLoginRequestFromForm({
        tenantInput: { value: "tenant-form" },
        employeeInput: { value: "EMP-FORM" },
        passwordInput: { value: "FormPass!" },
        requestedScopes: ["workspace:use"]
      }),
      {
        tenant_id: "tenant-form",
        employee_id: "EMP-FORM",
        password: "FormPass!",
        requested_scopes: ["workspace:use"],
        ttl_seconds: 3600
      }
    );
  });

  it("rejects malformed credential login requests and summaries", () => {
    for (const input of [
      {},
      { tenantId: "", employeeId: "EMP-001", password: "x" },
      { tenantId: "tenant", employeeId: "", password: "x" },
      { tenantId: "tenant", employeeId: "EMP-001", password: "" },
      { tenantId: "tenant", employeeId: "EMP-001", password: "x", requestedScopes: [] },
      { tenantId: "tenant", employeeId: "EMP-001", password: "x", requestedScopes: [""] },
      { tenantId: "tenant", employeeId: "EMP-001", password: "x", ttlSeconds: 0 },
      { tenantId: "tenant", employeeId: "EMP-001", password: "x", ttlSeconds: 86401 },
      {
        tenantId: "tenant",
        employeeId: "EMP-001",
        password: "x",
        requestedScopes: ["workspace:use"],
        scopes: ["documents:upload"]
      }
    ]) {
      assert.throws(
        () => buildCredentialLoginRequest(input),
        error => error instanceof CredentialLoginSurfaceError
      );
    }
    assert.throws(
      () => buildCredentialLoginSurfaceSummary({}),
      error =>
        error instanceof CredentialLoginSurfaceError &&
        error.status === "CREDENTIAL_LOGIN_SUMMARY_INVALID"
    );
  });

  it("rejects unsupported request fields before submit", () => {
    assertCredentialLoginRequestShape({
      tenant_id: "tenant-a",
      employee_id: "EMP-001",
      password: "Nuri1004!",
      requested_scopes: ["workspace:use"],
      ttl_seconds: 3600
    });

    for (const payload of [
      null,
      [],
      { tenant_id: "tenant-a", password_hash: "secret" },
      { tenant_id: "tenant-a", access_token: "raw" }
    ]) {
      assert.throws(
        () => assertCredentialLoginRequestShape(payload),
        error => error instanceof CredentialLoginSurfaceError
      );
    }
  });
});
