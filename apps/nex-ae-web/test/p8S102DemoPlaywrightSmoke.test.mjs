import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import { runP8S102DemoPlaywrightSmoke } from "../scripts/runP8S102DemoPlaywrightSmoke.mjs";

const PACKAGE = JSON.parse(
  readFileSync(new URL("../package.json", import.meta.url), "utf-8")
);

function smokeEnv() {
  return {
    NEX_P8_S102_WEB_URL: "http://127.0.0.1:5227/",
    NEX_P8_S102_TENANT_ID: "tenant-p8-s102",
    NEX_P8_S102_EMPLOYEE_ID: "EMP-P8-S102",
    NEX_P8_S102_PASSWORD: "private-p8-s102",
    NEX_P8_S102_PROMPT: "canonical prompt"
  };
}

function fakePlaywright() {
  const requestHandlers = [];
  const selectorStates = [];
  const fields = {};
  const emit = (method, route) =>
    requestHandlers.forEach(handler =>
      handler({ method: () => method, url: () => `http://127.0.0.1:5227${route}` })
    );
  const page = {
    on(eventName, handler) {
      if (eventName === "request") requestHandlers.push(handler);
    },
    async addInitScript() {},
    async goto() {
      emit("GET", "/ae-api/api/v1/auth/session");
    },
    async fill(selector, value) {
      fields[selector] = value;
    },
    async click(selector) {
      if (selector === "#credential-login-submit-button") {
        emit("POST", "/ae-api/api/v1/auth/session/login");
      } else if (selector === "#composer button[type='submit']") {
        emit("POST", "/ae-api/api/v1/chat/interactions");
        emit("GET", "/ae-api/api/v1/chat/interactions/p8-s102/progress");
      } else if (selector === "#credential-logout-button") {
        emit("POST", "/ae-api/api/v1/auth/session/logout");
      }
    },
    async waitForSelector(selector, options = {}) {
      selectorStates.push({ selector, state: options.state });
    },
    async uncheck() {},
    async waitForFunction() {},
    async evaluate() {
      return {
        userPromptVisible: true,
        committedResultVisible: true,
        projectVisible: true,
        amountVisible: true,
        applicationVisible: true
      };
    }
  };
  return {
    selectorStates,
    playwright: {
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
    }
  };
}

describe("P8-S102 protected demo Playwright contract", () => {
  it("drives the authenticated prompt journey with metadata-only evidence", async () => {
    const fake = fakePlaywright();
    const evidence = await runP8S102DemoPlaywrightSmoke({
      environ: smokeEnv(),
      importPlaywright: async () => fake.playwright
    });

    assert.equal(evidence.status, "PASS");
    assert.equal(evidence.checks.natural_language_prompt_submitted, true);
    assert.equal(evidence.checks.committed_voucher_result_visible, true);
    assert.equal(evidence.checks.canonical_chat_routes_called, true);
    assert.deepEqual(fake.selectorStates[0], {
      selector: "#credential-login-feedback[data-severity='success']",
      state: "attached"
    });
    assert.equal(JSON.stringify(evidence).includes(smokeEnv().NEX_P8_S102_PASSWORD), false);
  });

  it("is registered and fails closed when required configuration is absent", async () => {
    assert.equal(
      PACKAGE.scripts["smoke:p8-s102-demo-playwright"],
      "node scripts/runP8S102DemoPlaywrightSmoke.mjs"
    );
    const evidence = await runP8S102DemoPlaywrightSmoke({ environ: {} });
    assert.equal(evidence.status, "FAIL");
    assert.equal(evidence.failure_code, "required_env_missing");
  });
});
