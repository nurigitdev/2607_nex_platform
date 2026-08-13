import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  EMPLOYEE_ID_ENV,
  PASSWORD_ENV,
  TENANT_ID_ENV,
  WEB_URL_ENV,
  assertPlaywrightSmokeEvidenceRedacted,
  formatSummary,
  runCredentialLoginPlaywrightSmoke,
  safeFetchRuntimeConfig
} from "../scripts/runCredentialLoginPlaywrightSmoke.mjs";

function smokeEnv() {
  return {
    [WEB_URL_ENV]: "http://127.0.0.1:5227/",
    [TENANT_ID_ENV]: "tenant-playwright-0270",
    [EMPLOYEE_ID_ENV]: "EMP-PLAYWRIGHT-0270",
    [PASSWORD_ENV]: "playwright-secret-0270"
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
  let state = "anonymous";
  return {
    closed: false,
    on(eventName, handler) {
      handlers[eventName].push(handler);
    },
    async addInitScript(_script, config) {
      this.runtimeConfig = config;
    },
    async goto() {
      emitRequest(handlers, "GET", "http://127.0.0.1:5227/ae-api/api/v1/auth/session", 401);
    },
    async fill(selector, value) {
      fields[selector] = value;
    },
    async click(selector) {
      if (selector === "#credential-login-submit-button") {
        fields["#credential-password"] = "";
        state = "authenticated";
        emitRequest(
          handlers,
          "POST",
          "http://127.0.0.1:5227/ae-api/api/v1/auth/session/login",
          200
        );
      }
      if (selector === "#credential-logout-button") {
        state = "logged_out";
        emitRequest(
          handlers,
          "POST",
          "http://127.0.0.1:5227/ae-api/api/v1/auth/session/logout",
          200
        );
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
      if (selector === "#credential-login-summary") {
        return "employee present";
      }
      return "";
    },
    async inputValue(selector) {
      return fields[selector] || "";
    },
    async isVisible(selector) {
      return selector === "#credential-logout-button" && state === "authenticated";
    }
  };
}

function emitRequest(handlers, method, url, status) {
  handlers.request.forEach(handler =>
    handler({
      method: () => method,
      url: () => url
    })
  );
  handlers.response.forEach(handler =>
    handler({
      status: () => status,
      url: () => url
    })
  );
}

describe("AE Web credential-login Playwright smoke", () => {
  it("drives the credential login and logout DOM flow through same-origin routes", async () => {
    const env = smokeEnv();
    const evidence = await runCredentialLoginPlaywrightSmoke({
      environ: env,
      importPlaywright: async () => fakePlaywright()
    });
    const serialized = JSON.stringify(evidence);

    assert.equal(evidence.status, "PASS");
    assert.equal(evidence.runner.tool, "Playwright");
    assert.equal(evidence.browser_runtime_config.ae_base_url, "/ae-api");
    assert.equal(evidence.browser_observations.route_guard_status_after_login, "allowed");
    assert.equal(evidence.browser_observations.route_guard_status_after_logout, "blocked");
    assert.equal(evidence.request_observations.ae_api_request_count, 3);
    assert.equal(evidence.checks.password_cleared_after_submit, true);
    assert.equal(serialized.includes(env[PASSWORD_ENV]), false);
    assert.equal(formatSummary(evidence), (
      "ae_web_credential_login_playwright_smoke=pass " +
      "browser=chromium route_guard=allowed requests=3"
    ));
  });

  it("reports missing env and browser launch failures without leaking inputs", async () => {
    const missing = await runCredentialLoginPlaywrightSmoke({
      environ: {},
      importPlaywright: async () => fakePlaywright()
    });
    const failedLaunch = await runCredentialLoginPlaywrightSmoke({
      environ: smokeEnv(),
      importPlaywright: async () => fakePlaywright({ launchFails: true })
    });

    assert.equal(missing.status, "FAIL");
    assert.equal(missing.failure_code, "required_env_missing");
    assert.equal(failedLaunch.status, "FAIL");
    assert.equal(failedLaunch.failure_code, "Error");
    assert.equal(
      formatSummary(failedLaunch),
      "ae_web_credential_login_playwright_smoke=fail reason=Error"
    );
  });

  it("keeps browser runtime config and evidence redaction explicit", () => {
    const config = safeFetchRuntimeConfig();

    assert.deepEqual(config.features, {
      document_detail_enabled: true,
      upload_submit_enabled: true,
      retrieval_submit_enabled: true,
      fetch_clients_enabled: true
    });
    assert.throws(
      () =>
        assertPlaywrightSmokeEvidenceRedacted(
          { leak: "playwright-secret-0270" },
          smokeEnv()
        ),
      /PASSWORD/
    );
    assert.throws(
      () => assertPlaywrightSmokeEvidenceRedacted({ leak: "database_url" }, {}),
      /server material/
    );
  });
});
