import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { runP8S112ProjectMembershipPlaywrightSmoke } from "../scripts/runP8S112ProjectMembershipPlaywrightSmoke.mjs";

function smokeEnv() {
  return {
    NEX_P8_S112_WEB_URL: "http://127.0.0.1:5212/",
    NEX_P8_S112_TENANT_ID: "tenant-p8-s112",
    NEX_P8_S112_EMPLOYEE_ID: "EMP-S112",
    NEX_P8_S112_PASSWORD: "not-recorded"
  };
}

function fakePlaywright() {
  const requestHandlers = [];
  const page = {
    on(eventName, handler) {
      if (eventName === "request") requestHandlers.push(handler);
    },
    async addInitScript() {},
    async goto() {},
    async fill() {},
    async uncheck() {},
    async waitForSelector() {},
    async click(selector) {
      const routes = {
        "#credential-login-submit-button": "/ae-api/api/v1/auth/session/login",
        "#composer button[type='submit']": "/ae-api/api/v1/chat/interactions",
        "#credential-logout-button": "/ae-api/api/v1/auth/session/logout"
      };
      const route = routes[selector];
      if (route) {
        requestHandlers.forEach(handler =>
          handler({
            method: () => "POST",
            url: () => `http://127.0.0.1:5212${route}`
          })
        );
      }
      if (selector === "#composer button[type='submit']") {
        requestHandlers.forEach(handler =>
          handler({
            method: () => "GET",
            url: () =>
              "http://127.0.0.1:5212/ae-api/api/v1/chat/interactions/example/progress"
          })
        );
      }
    },
    async evaluate() {
      return {
        authenticatedShell: true,
        resultVisible: true,
        requestedCountVisible: true,
        appliedCountVisible: true,
        rejectedCountVisible: true,
        addedVisible: true,
        nameMismatchVisible: true,
        notFoundVisible: true
      };
    }
  };
  return {
    chromium: {
      async launch() {
        return {
          async newPage() {
            return page;
          },
          async close() {}
        };
      }
    }
  };
}

describe("P8-S112 project membership Playwright smoke", () => {
  it("maps its protected journey onto the shared credential harness contract", async () => {
    const evidence = await runP8S112ProjectMembershipPlaywrightSmoke({
      environ: smokeEnv(),
      importPlaywright: async () => fakePlaywright()
    });

    assert.equal(evidence.status, "PASS");
    assert.equal(evidence.checks.same_origin_login_called, true);
    assert.equal(evidence.checks.same_origin_logout_called, true);
    assert.equal(evidence.checks.route_guard_allowed_after_login, true);
    assert.equal(evidence.checks.logout_feedback_logged_out, true);
    assert.equal(evidence.checks.item_outcomes_visible, true);
  });

  it("fails closed when protected browser inputs are incomplete", async () => {
    const evidence = await runP8S112ProjectMembershipPlaywrightSmoke({
      environ: {},
      importPlaywright: async () => fakePlaywright()
    });

    assert.equal(evidence.status, "FAIL");
    assert.equal(evidence.failure_code, "required_env_missing");
    assert.equal(evidence.checks.redacted_evidence, true);
  });
});
