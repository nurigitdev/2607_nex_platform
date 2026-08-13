import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_WEB_AUTHENTICATED_UPLOAD_WORKFLOW_SCHEMA_VERSION,
  AuthenticatedUploadWorkflowError,
  buildAuthenticatedUploadWorkflowSummary,
  runAuthenticatedUploadWorkflow
} from "../src/authenticatedUploadWorkflow.js";
import {
  buildUploadFileMetadata,
  buildUploadOwnershipRef
} from "../src/uploadSurface.js";

const uploadSha256 = "7a1ff859bf541f6f40b662f7f9a3f8401f8f34425646d651c7537e6f9f4e0072";

function fileMetadata() {
  return buildUploadFileMetadata({
    file: {
      name: "authenticated-upload.md",
      type: "text/markdown",
      size: 1536
    },
    sourceSha256: uploadSha256
  });
}

function loginRequest() {
  return {
    tenant_id: "tenant-upload-0273",
    employee_id: "EMP-0273",
    password: "upload-secret-0273",
    requested_scopes: ["workspace:use", "documents:upload"],
    ttl_seconds: 1800
  };
}

function createFakeFetch() {
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    const method = options.method || "GET";
    const body = options.body ? JSON.parse(options.body) : null;
    calls.push({
      method,
      url,
      credentials: options.credentials,
      bodyKeys: body ? Object.keys(body).sort() : []
    });

    if (url === "/ae-api/api/v1/auth/session" && method === "GET") {
      return jsonResponse({ ok: false, status: 401, payload: {} });
    }
    if (url === "/ae-api/api/v1/auth/session/login" && method === "POST") {
      return jsonResponse({ payload: activeSession(body) });
    }
    if (url === "/ae-api/api/v1/uploads" && method === "POST") {
      return jsonResponse({ status: 202, payload: uploadHandoff(body) });
    }
    if (url === "/ae-api/api/v1/auth/session/logout" && method === "POST") {
      return jsonResponse({
        payload: activeSession({}, { status: "REVOKED", session_id: "session-upload-0273" })
      });
    }
    return jsonResponse({
      ok: false,
      status: 404,
      payload: { error_code: "ae.fake_route_not_found" }
    });
  };
  return { calls, fetchImpl };
}

function activeSession(body = {}, overrides = {}) {
  return {
    browser_session_schema_version: "oa_browser_session.v1",
    session_id: "session-upload-0273",
    status: "ACTIVE",
    issuer: "nex-oa",
    audience: "nex-ae-api",
    token_use: "user",
    tenant_ref: { type: "oa.tenant", id: body.tenant_id || "tenant-upload-0273" },
    subject_ref: { type: "oa.user", id: "user-upload-0273" },
    scopes: body.requested_scopes || ["workspace:use", "documents:upload"],
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

function uploadHandoff(body) {
  return {
    upload_handoff_schema_version: "ae_upload_handoff.v1",
    upload_handoff_id: "handoff-upload-0273",
    workspace_id: body.workspace_id,
    tenant_id: body.tenant_id,
    owner_user_id: body.owner_user_id,
    ownership_ref: buildUploadOwnershipRef({
      tenantId: body.tenant_id,
      ownerUserId: body.owner_user_id,
      uploadedByUserId: body.uploaded_by_user_id
    }),
    status: "QUEUED",
    dedupe: {
      status: "CREATED"
    },
    source: {
      filename: body.filename,
      content_type: body.content_type,
      size_bytes: body.size_bytes,
      source_sha256: body.source_sha256
    },
    cx_document_ref: {
      document_id: "doc-upload-0273"
    },
    links: {
      upload_handoff: "/api/v1/uploads/handoff-upload-0273",
      document_detail: "/api/v1/documents/doc-upload-0273"
    }
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

describe("authenticated upload workflow", () => {
  it("runs login, owner-scoped upload, and logout through same-origin fetch clients", async () => {
    const { calls, fetchImpl } = createFakeFetch();

    const workflow = await runAuthenticatedUploadWorkflow({
      baseUrl: "/ae-api",
      fetchImpl,
      loginRequest: loginRequest(),
      workspaceId: "workspace-upload-0273",
      fileMetadata: fileMetadata()
    });
    const summary = buildAuthenticatedUploadWorkflowSummary(workflow);
    const serialized = JSON.stringify({ workflow, calls });

    assert.equal(
      workflow.authenticated_upload_workflow_schema_version,
      AE_WEB_AUTHENTICATED_UPLOAD_WORKFLOW_SCHEMA_VERSION
    );
    assert.equal(workflow.current_session.status, "anonymous");
    assert.equal(workflow.authenticated_session.owner_user_id, "user-upload-0273");
    assert.equal(workflow.upload_result.status, "QUEUED");
    assert.equal(workflow.upload_result.document_id, "doc-upload-0273");
    assert.equal(workflow.logout_session.status, "anonymous");
    assert.deepEqual(calls.map(call => `${call.method} ${call.url}`), [
      "GET /ae-api/api/v1/auth/session",
      "POST /ae-api/api/v1/auth/session/login",
      "POST /ae-api/api/v1/uploads",
      "POST /ae-api/api/v1/auth/session/logout"
    ]);
    assert.equal(calls.every(call => call.credentials === "same-origin"), true);
    assert.equal(summary.checks_passed, true);
    assert.equal(summary.owner_scope_source, "oa_session_claims");
    assert.equal(summary.route, "/api/v1/uploads");
    assert.doesNotMatch(
      serialized,
      /upload-secret-0273|content_text|content_base64|service_token|database_url|provider_url/
    );
  });

  it("rejects missing login and owner-scope-invalid sessions", async () => {
    await assert.rejects(
      () =>
        runAuthenticatedUploadWorkflow({
          workspaceId: "workspace-upload-0273",
          fileMetadata: fileMetadata()
        }),
      error =>
        error instanceof AuthenticatedUploadWorkflowError &&
        error.status === "LOGIN_REQUEST_REQUIRED"
    );
    await assert.rejects(
      () =>
        runAuthenticatedUploadWorkflow({
          loginRequest: loginRequest(),
          fileMetadata: fileMetadata()
        }),
      error =>
        error instanceof AuthenticatedUploadWorkflowError &&
        error.status === "WORKSPACE_ID_REQUIRED"
    );
    await assert.rejects(
      () =>
        runAuthenticatedUploadWorkflow({
          loginRequest: loginRequest(),
          workspaceId: "workspace-upload-0273",
          fileMetadata: fileMetadata(),
          sessionClient: {
            clientMode: "fetch",
            async getCurrentSession() {
              return { status: "anonymous", reason: "test" };
            },
            async login() {
              return { status: "anonymous", reason: "bad" };
            },
            async logout() {
              return { status: "anonymous", reason: "logout" };
            }
          },
          uploadClient: {
            clientMode: "fetch",
            async submitUploadDraft() {
              throw new Error("must not upload");
            }
          }
        }),
      error =>
        error instanceof AuthenticatedUploadWorkflowError &&
        error.status === "OWNER_SCOPE_REQUIRED"
    );
    assert.throws(
      () => buildAuthenticatedUploadWorkflowSummary({}),
      error =>
        error instanceof AuthenticatedUploadWorkflowError &&
        error.status === "WORKFLOW_SUMMARY_INVALID"
    );
  });
});
