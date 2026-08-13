import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_SCHEMA_VERSION,
  EMPLOYEE_ID_ENV,
  PASSWORD_ENV,
  SOURCE_SHA256_ENV,
  TENANT_ID_ENV,
  WEB_URL_ENV,
  assertAuthenticatedUploadPlaywrightSmokeEvidenceRedacted,
  formatSummary,
  main,
  runAuthenticatedUploadPlaywrightSmoke,
  safeFetchRuntimeConfig
} from "../scripts/runAuthenticatedUploadPlaywrightSmoke.mjs";

const uploadSha256 =
  "7a1ff859bf541f6f40b662f7f9a3f8401f8f34425646d651c7537e6f9f4e0072";

function smokeEnv() {
  return {
    [WEB_URL_ENV]: "http://127.0.0.1:5228/",
    [TENANT_ID_ENV]: "tenant-upload-playwright-0274",
    [EMPLOYEE_ID_ENV]: "EMP-UPLOAD-0274",
    [PASSWORD_ENV]: "upload-playwright-secret-0274",
    [SOURCE_SHA256_ENV]: uploadSha256
  };
}

function fakePlaywright({ launchFails = false } = {}) {
  const page = fakePage();
  return {
    chromium: {
      async launch() {
        if (launchFails) {
          throw new Error("browser launch failed");
        }
        return {
          async newPage() {
            return page;
          },
          async close() {
            page.closed = true;
          }
        };
      }
    }
  };
}

function fakePage() {
  const handlers = { request: [], response: [] };
  const fields = {};
  const selectedFile = {};
  let state = "anonymous";
  let uploadSubmitted = false;
  return {
    closed: false,
    on(eventName, handler) {
      handlers[eventName].push(handler);
    },
    async addInitScript(_script, config) {
      this.runtimeConfig = config;
    },
    async goto() {
      emitRequest(handlers, {
        method: "GET",
        url: "http://127.0.0.1:5228/ae-api/api/v1/auth/session",
        status: 401
      });
    },
    async fill(selector, value) {
      fields[selector] = value;
    },
    async setInputFiles(selector, file) {
      selectedFile[selector] = file;
    },
    async click(selector) {
      if (selector === "#credential-login-submit-button") {
        fields["#credential-password"] = "";
        state = "authenticated";
        emitRequest(handlers, {
          method: "POST",
          url: "http://127.0.0.1:5228/ae-api/api/v1/auth/session/login",
          status: 200
        });
      }
      if (selector === "#upload-submit-button") {
        uploadSubmitted = true;
        const file = selectedFile["#upload-file-input"];
        emitRequest(handlers, {
          method: "POST",
          url: "http://127.0.0.1:5228/ae-api/api/v1/uploads",
          status: 202,
          body: {
            workspace_id: "workspace-nex-alpha",
            filename: file.name,
            content_type: file.mimeType,
            size_bytes: file.buffer.length,
            source_sha256: fields["#upload-source-sha256"],
            tenant_id: fields["#credential-tenant-id"],
            owner_user_id: "user-upload-playwright-0274",
            uploaded_by_user_id: "user-upload-playwright-0274",
            ownership_ref: {
              tenant_ref: { type: "oa.tenant", id: fields["#credential-tenant-id"] },
              owner_subject_ref: {
                type: "oa.user",
                id: "user-upload-playwright-0274"
              },
              uploaded_by_subject_ref: {
                type: "oa.user",
                id: "user-upload-playwright-0274"
              }
            }
          }
        });
      }
      if (selector === "#credential-logout-button") {
        state = "logged_out";
        emitRequest(handlers, {
          method: "POST",
          url: "http://127.0.0.1:5228/ae-api/api/v1/auth/session/logout",
          status: 200
        });
      }
    },
    async waitForSelector() {},
    async waitForFunction() {},
    async textContent(selector) {
      if (selector === "#credential-login-feedback") {
        return state === "logged_out"
          ? "로그아웃되었습니다."
          : "로그인 세션이 활성화되었습니다.";
      }
      if (selector === "#session-route-guard-summary") {
        return state === "logged_out" ? "guard blocked" : "guard allowed";
      }
      if (selector === "#upload-feedback") {
        return uploadSubmitted
          ? "업로드 handoff가 접수되었습니다."
          : "업로드 전송 준비가 완료되었습니다.";
      }
      if (selector === "#upload-file-metadata-summary") {
        const file = selectedFile["#upload-file-input"];
        return `${file?.name || "empty"} hash present`;
      }
      if (selector === "#upload-client-summary") {
        return uploadSubmitted
          ? "client fetch operation succeeded handoff handoff-0274 document doc-0274"
          : "client fetch operation ready";
      }
      return "";
    },
    async inputValue(selector) {
      return fields[selector] || "";
    }
  };
}

function emitRequest(handlers, { method, url, status, body = null }) {
  handlers.request.forEach(handler =>
    handler({
      method: () => method,
      url: () => url,
      postDataJSON: () => body
    })
  );
  handlers.response.forEach(handler =>
    handler({
      status: () => status,
      url: () => url
    })
  );
}

describe("AE Web authenticated upload Playwright smoke", () => {
  it("drives login, metadata-only upload, and logout through same-origin routes", async () => {
    const env = smokeEnv();
    const evidence = await runAuthenticatedUploadPlaywrightSmoke({
      environ: env,
      importPlaywright: async () => fakePlaywright()
    });
    const serialized = JSON.stringify(evidence);

    assert.equal(
      evidence.smoke_schema_version,
      AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_SCHEMA_VERSION
    );
    assert.equal(evidence.status, "PASS");
    assert.equal(evidence.browser_runtime_config.ae_base_url, "/ae-api");
    assert.equal(evidence.request_observations.ae_api_request_count, 4);
    assert.equal(evidence.request_observations.upload_response_status, 202);
    assert.equal(evidence.browser_observations.upload_feedback_status, "accepted");
    assert.equal(evidence.checks.upload_body_metadata_only, true);
    assert.equal(evidence.checks.upload_body_owner_scope_present, true);
    assert.equal(evidence.checks.password_cleared_after_submit, true);
    assert.equal(serialized.includes(env[PASSWORD_ENV]), false);
    assert.equal(serialized.includes(env[SOURCE_SHA256_ENV]), false);
    assert.equal(
      formatSummary(evidence),
      "ae_web_authenticated_upload_playwright_smoke=pass " +
        "browser=chromium upload=accepted status=202 requests=4"
    );
  });

  it("reports missing env and launch failures without leaking input material", async () => {
    const missing = await runAuthenticatedUploadPlaywrightSmoke({
      environ: {},
      importPlaywright: async () => fakePlaywright()
    });
    const failedLaunch = await runAuthenticatedUploadPlaywrightSmoke({
      environ: smokeEnv(),
      importPlaywright: async () => fakePlaywright({ launchFails: true })
    });

    assert.equal(missing.status, "FAIL");
    assert.equal(missing.failure_code, "required_env_missing");
    assert.equal(failedLaunch.status, "FAIL");
    assert.equal(failedLaunch.failure_code, "Error");
    assert.equal(
      formatSummary(failedLaunch),
      "ae_web_authenticated_upload_playwright_smoke=fail reason=Error"
    );
  });

  it("keeps runtime config, redaction, and CLI modes explicit", async () => {
    const config = safeFetchRuntimeConfig();
    const jsonLines = [];
    const summaryLines = [];

    assert.deepEqual(config.features, {
      document_detail_enabled: true,
      upload_submit_enabled: true,
      retrieval_submit_enabled: true,
      fetch_clients_enabled: true
    });
    assert.throws(
      () =>
        assertAuthenticatedUploadPlaywrightSmokeEvidenceRedacted(
          { leak: "upload-playwright-secret-0274" },
          smokeEnv()
        ),
      /PASSWORD/
    );
    assert.throws(
      () =>
        assertAuthenticatedUploadPlaywrightSmokeEvidenceRedacted(
          { leak: uploadSha256 },
          smokeEnv()
        ),
      /SOURCE_SHA256/
    );
    assert.throws(
      () =>
        assertAuthenticatedUploadPlaywrightSmokeEvidenceRedacted(
          { leak: "database_url" },
          {}
        ),
      /server material/
    );

    assert.equal(
      await main([], line => jsonLines.push(line)),
      1
    );
    assert.equal(
      await main(["--summary"], line => summaryLines.push(line)),
      1
    );
    assert.equal(JSON.parse(jsonLines.at(0)).failure_code, "required_env_missing");
    assert.match(summaryLines.at(0), /reason=required_env_missing/);
  });
});
