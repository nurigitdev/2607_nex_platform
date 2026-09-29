import test from "node:test";
import assert from "node:assert/strict";

import {
  ENV,
  assertEvidenceRedacted,
  formatSummary,
  groundedGenerationRouteChecks,
  normalizeInteractionRoute,
  runGroundedGenerationPlaywrightSmoke,
  safeDocumentBootstrap,
  safeErrorDetail,
  safeFetchRuntimeConfig,
  safeWorkspaceBootstrap,
  sameOriginAeApiRoute
} from "../scripts/runGroundedGenerationPlaywrightSmoke.mjs";

const environ = {
  [ENV.webUrl]: "http://127.0.0.1:31090/",
  [ENV.tenantId]: "tenant-1090",
  [ENV.ownerUserId]: "owner-user-1090",
  [ENV.employeeId]: "employee-1090",
  [ENV.password]: "protected-password-1090",
  [ENV.documentId]: "7d88f119-d9c7-4c8a-a310-c3eea6613f64",
  [ENV.workspaceId]: "7f4c34be-6d3f-4296-884d-b823904cf5df",
  [ENV.chatDocumentId]: "6ba55095-00c3-42c5-9f67-f0699dd99617"
};

test("fails closed before launching when protected inputs are absent", async () => {
  const result = await runGroundedGenerationPlaywrightSmoke({ environ: {} });
  assert.equal(result.status, "FAIL");
  assert.equal(result.failure_code, "required_env_missing");
  assert.equal(result.observations.launch_attempted, false);
});

test("builds safe fetch and document bootstrap inputs", () => {
  const runtime = safeFetchRuntimeConfig();
  const documents = safeDocumentBootstrap(environ);
  const workspace = safeWorkspaceBootstrap(environ);
  assert.equal(runtime.client_mode, "fetch");
  assert.equal(runtime.ae_base_url, "/ae-api");
  assert.equal(documents.documents[0].document_id, environ[ENV.documentId]);
  assert.equal(documents.documents[0].best_score, 0.9);
  assert.equal(workspace.workspace_id, environ[ENV.workspaceId]);
  assert.equal(workspace.chat_document_id, environ[ENV.chatDocumentId]);
});

test("normalizes lifecycle routes and reports required calls", () => {
  const routes = [
    ["POST", "/ae-api/api/v1/chat/interactions"],
    ["GET", "/ae-api/api/v1/chat/interactions/id-1/progress"],
    ["POST", "/ae-api/api/v1/chat/interactions/id-1/refresh"],
    ["GET", "/ae-api/api/v1/chat/interactions/id-1/response"],
    ["GET", "/ae-api/api/v1/chat/interactions/id-1/citation-quality"]
  ].map(([method, route]) => ({ method, route: normalizeInteractionRoute(route) }));
  assert.deepEqual(groundedGenerationRouteChecks(routes), {
    interaction_admission_called: true,
    progress_called: true,
    refresh_called: true,
    generated_response_called: true,
    citation_quality_called: true
  });
  assert.equal(
    sameOriginAeApiRoute("http://local/ae-api/api/v1/chat/interactions"),
    "/ae-api/api/v1/chat/interactions"
  );
  assert.equal(
    normalizeInteractionRoute("/ae-api/api/v1/documents/private-document-id"),
    "/ae-api/api/v1/documents/{document_id}"
  );
  assert.equal(sameOriginAeApiRoute("not-a-url"), null);
});

test("redacts protected values and formats bounded summaries", () => {
  const passing = {
    status: "PASS",
    browser_observations: { display_mode: "VERIFIED_RESPONSE", timeline_event_count: 6 },
    request_observations: { ae_api_request_count: 8 }
  };
  assert.equal(
    formatSummary(passing),
    "ae_web_grounded_generation_playwright_smoke=pass " +
      "display=VERIFIED_RESPONSE events=6 requests=8"
  );
  assert.match(formatSummary({ status: "FAIL", failure_code: "boom" }), /boom/);
  assert.doesNotThrow(() => assertEvidenceRedacted({ safe: true }, environ));
  assert.throws(
    () => assertEvidenceRedacted({ leaked: environ[ENV.password] }, environ),
    /leaked/
  );
  assert.equal(
    safeErrorDetail("Generated response content integrity is inconsistent."),
    "Generated response content integrity is inconsistent."
  );
  assert.equal(safeErrorDetail("private: value"), null);
  assert.equal(
    safeErrorDetail("ID 7d88f119-d9c7-4c8a-a310-c3eea6613f64 was invalid."),
    null
  );
});
