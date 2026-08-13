#!/usr/bin/env node
import { pathToFileURL } from "node:url";

import {
  AE_WEB_AUTHENTICATED_UPLOAD_WORKFLOW_SCHEMA_VERSION,
  buildAuthenticatedUploadWorkflowSummary,
  runAuthenticatedUploadWorkflow
} from "../src/authenticatedUploadWorkflow.js";
import {
  buildUploadFileMetadata,
  buildUploadOwnershipRef
} from "../src/uploadSurface.js";

export const AE_WEB_AUTHENTICATED_UPLOAD_FETCH_SMOKE_SCHEMA_VERSION =
  "ae_web_authenticated_upload_fetch_smoke.v1";

const SMOKE_PASSWORD = "slice-0273-upload-secret";
const LOGIN_REQUEST = {
  tenant_id: "tenant-slice-0273",
  employee_id: "EMP-0273",
  password: SMOKE_PASSWORD,
  requested_scopes: ["workspace:use", "documents:upload"],
  ttl_seconds: 1800
};
const FILE_METADATA = buildUploadFileMetadata({
  file: {
    name: "slice-0273-upload.md",
    type: "text/markdown",
    size: 1536
  },
  sourceSha256: "7a1ff859bf541f6f40b662f7f9a3f8401f8f34425646d651c7537e6f9f4e0072"
});

export async function runAuthenticatedUploadFetchSmoke() {
  const fakeFetch = createFakeAuthenticatedUploadFetch();
  const workflow = await runAuthenticatedUploadWorkflow({
    baseUrl: "/ae-api",
    fetchImpl: fakeFetch.fetchImpl,
    loginRequest: LOGIN_REQUEST,
    workspaceId: "workspace-slice-0273",
    fileMetadata: FILE_METADATA
  });
  const summary = buildAuthenticatedUploadWorkflowSummary(workflow);
  const checks = {
    workflow_schema_matches:
      workflow.authenticated_upload_workflow_schema_version ===
      AE_WEB_AUTHENTICATED_UPLOAD_WORKFLOW_SCHEMA_VERSION,
    workflow_checks_passed: summary.checks_passed,
    same_origin_sequence_matches: uploadRouteSequence(fakeFetch.calls),
    upload_body_owner_from_session_claims:
      fakeFetch.uploadBody?.owner_user_id === "user-slice-0273",
    upload_body_metadata_only:
      fakeFetch.uploadBody?.filename === "slice-0273-upload.md" &&
      fakeFetch.uploadBody?.content_type === "text/markdown" &&
      fakeFetch.uploadBody?.size_bytes === 1536 &&
      typeof fakeFetch.uploadBody?.source_sha256 === "string" &&
      !("content_text" in fakeFetch.uploadBody) &&
      !("content_base64" in fakeFetch.uploadBody),
    logout_returns_anonymous: workflow.logout_session.status === "anonymous",
    live_network_not_used: true
  };
  const evidence = {
    smoke_schema_version: AE_WEB_AUTHENTICATED_UPLOAD_FETCH_SMOKE_SCHEMA_VERSION,
    evidence_generated_at: new Date().toISOString(),
    status: Object.values(checks).every(Boolean) ? "PASS" : "FAIL",
    runner: {
      mode: "deterministic_fake_fetch",
      slice: "Slice 0273",
      live_network_used: false,
      postgresql_used: false,
      browser_api_path: "/ae-api"
    },
    workflow: {
      schema_version: workflow.authenticated_upload_workflow_schema_version,
      summary,
      current_session: workflow.current_session,
      authenticated_session: workflow.authenticated_session,
      upload_file_metadata: workflow.upload_file_metadata,
      upload_draft: workflow.upload_draft,
      upload_result: workflow.upload_result,
      logout_session: workflow.logout_session
    },
    request_observations: {
      fetch_call_count: fakeFetch.calls.length,
      routes: fakeFetch.calls,
      upload_body_summary: uploadBodySummary(fakeFetch.uploadBody)
    },
    checks,
    redaction: {
      rawPasswordInEvidence: false,
      rawSourceInEvidence: false,
      rawTokenInEvidence: false,
      serviceCredentialInEvidence: false,
      databaseEndpointInEvidence: false,
      providerEndpointInEvidence: false
    }
  };
  assertAuthenticatedUploadFetchSmokeEvidenceRedacted(evidence, {
    rawPassword: SMOKE_PASSWORD
  });
  return evidence;
}

export function formatSummary(evidence) {
  if (evidence.status === "PASS") {
    return (
      "ae_web_authenticated_upload_fetch_smoke=pass " +
      `mode=${evidence.runner.mode} ` +
      `route=${evidence.workflow.summary.route} ` +
      `status=${evidence.workflow.summary.upload_status} ` +
      `fetch_calls=${evidence.request_observations.fetch_call_count}`
    );
  }
  return "ae_web_authenticated_upload_fetch_smoke=fail";
}

export function assertAuthenticatedUploadFetchSmokeEvidenceRedacted(
  evidence,
  { rawPassword } = {}
) {
  const serialized = JSON.stringify(evidence);
  if (rawPassword && serialized.includes(rawPassword)) {
    throw new Error("authenticated upload fetch smoke leaked raw password");
  }
  for (const fragment of [
    "access_" + "token",
    "content_" + "base64",
    "content_" + "text",
    `database_${"url"}`,
    `provider_${"url"}`,
    `service_${"token"}`,
    "/data/" + "nex-platform"
  ]) {
    if (serialized.includes(fragment)) {
      throw new Error("authenticated upload fetch smoke leaked server material");
    }
  }
}

export async function main(argv = process.argv.slice(2), output = console.log) {
  const summary = argv.includes("--summary");
  try {
    const evidence = await runAuthenticatedUploadFetchSmoke();
    output(summary ? formatSummary(evidence) : JSON.stringify(evidence, null, 2));
    return evidence.status === "PASS" ? 0 : 1;
  } catch (error) {
    output(
      "ae_web_authenticated_upload_fetch_smoke=fail " +
      `error=${error?.constructor?.name || "Error"}`
    );
    return 1;
  }
}

function createFakeAuthenticatedUploadFetch() {
  const state = {
    calls: [],
    uploadBody: null,
    fetchImpl: null
  };
  state.fetchImpl = async (url, options = {}) => {
    const method = options.method || "GET";
    const body = options.body ? JSON.parse(options.body) : null;
    state.calls.push({
      method,
      url,
      credentials: options.credentials || "same-origin",
      body_keys: body ? Object.keys(body).sort() : []
    });
    if (url === "/ae-api/api/v1/auth/session" && method === "GET") {
      return jsonResponse({ ok: false, status: 401, payload: {} });
    }
    if (url === "/ae-api/api/v1/auth/session/login" && method === "POST") {
      return jsonResponse({ payload: activeSession({ body }) });
    }
    if (url === "/ae-api/api/v1/uploads" && method === "POST") {
      state.uploadBody = body;
      return jsonResponse({ status: 202, payload: uploadHandoff(body) });
    }
    if (url === "/ae-api/api/v1/auth/session/logout" && method === "POST") {
      return jsonResponse({
        payload: activeSession({
          overrides: {
            status: "REVOKED"
          }
        })
      });
    }
    return jsonResponse({
      ok: false,
      status: 404,
      payload: { error_code: "ae.fake_route_not_found" }
    });
  };
  return state;
}

function activeSession({ body = {}, overrides = {} } = {}) {
  return {
    browser_session_schema_version: "oa_browser_session.v1",
    session_id: "session-slice-0273",
    status: "ACTIVE",
    issuer: "nex-oa",
    audience: "nex-ae-api",
    token_use: "user",
    tenant_ref: { type: "oa.tenant", id: body.tenant_id || "tenant-slice-0273" },
    subject_ref: { type: "oa.user", id: "user-slice-0273" },
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
    upload_handoff_id: "handoff-slice-0273",
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
      document_id: "doc-slice-0273"
    },
    links: {
      upload_handoff: "/api/v1/uploads/handoff-slice-0273",
      document_detail: "/api/v1/documents/doc-slice-0273"
    }
  };
}

function uploadRouteSequence(calls) {
  return (
    Array.isArray(calls) &&
    calls.map(call => `${call.method} ${call.url}`).join("|") ===
      [
        "GET /ae-api/api/v1/auth/session",
        "POST /ae-api/api/v1/auth/session/login",
        "POST /ae-api/api/v1/uploads",
        "POST /ae-api/api/v1/auth/session/logout"
      ].join("|") &&
    calls.every(call => call.credentials === "same-origin")
  );
}

function uploadBodySummary(body) {
  if (!body) return null;
  return {
    workspace_id: body.workspace_id,
    filename: body.filename,
    content_type: body.content_type,
    size_bytes: body.size_bytes,
    source_sha256_present: Boolean(body.source_sha256),
    tenant_id: body.tenant_id,
    owner_user_id: body.owner_user_id,
    uploaded_by_user_id: body.uploaded_by_user_id,
    ownership_ref_type: body.ownership_ref?.owner_subject_ref?.type || null,
    body_key_count: Object.keys(body).length,
    raw_source_included: false
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
