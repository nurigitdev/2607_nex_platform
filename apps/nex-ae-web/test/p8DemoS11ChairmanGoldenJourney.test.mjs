import assert from "node:assert/strict";
import test from "node:test";

import {
  assertP8DemoS11EvidenceRedacted,
  formatP8DemoS11Summary,
  p8DemoS11RuntimeConfig,
  publicP8DemoS11PlaywrightEvidence,
  runP8DemoS11ChairmanGoldenJourney,
  runP8DemoS11PostRestartRecovery
} from "../scripts/runP8DemoS11ChairmanGoldenJourney.mjs";

test("S11 runtime config admits fetch approval mode", () => {
  const config = p8DemoS11RuntimeConfig();
  assert.equal(config.client_mode, "fetch");
  assert.equal(config.ae_base_url, "/ae-api");
  assert.equal(config.features.approval_inbox_enabled, true);
});

test("S11 recovery runner also fails closed before importing Playwright", async () => {
  let imported = false;
  const result = await runP8DemoS11PostRestartRecovery({
    environ: {},
    importPlaywright: async () => {
      imported = true;
      return {};
    }
  });
  assert.equal(result.status, "FAIL");
  assert.equal(result.failure_code, "recovery_env_missing");
  assert.equal(imported, false);
});

test("S11 runner fails closed before importing Playwright", async () => {
  let imported = false;
  const result = await runP8DemoS11ChairmanGoldenJourney({
    environ: {},
    importPlaywright: async () => {
      imported = true;
      return {};
    }
  });
  assert.equal(result.status, "FAIL");
  assert.equal(result.failure_code, "required_env_missing");
  assert.equal(imported, false);
});

test("S11 runner classifies transient browser fetch failures safely", async () => {
  const result = await runP8DemoS11ChairmanGoldenJourney({
    environ: {
      NEX_P8_DEMO_S11_WEB_URL: "https://ae.nex-staging.test:8443",
      NEX_P8_DEMO_S11_TENANT_ID: "VO00",
      NEX_P8_DEMO_S11_REQUESTER_EMPLOYEE_ID: "1001",
      NEX_P8_DEMO_S11_REQUESTER_PASSWORD: "requester-password",
      NEX_P8_DEMO_S11_APPROVER_EMPLOYEE_ID: "2001",
      NEX_P8_DEMO_S11_APPROVER_PASSWORD: "approver-password",
      NEX_P8_DEMO_S11_PROMPT: "protected prompt"
    },
    importPlaywright: async () => ({
      chromium: {
        launch: async () => {
          throw new Error("page.evaluate: TypeError: Failed to fetch");
        }
      }
    })
  });

  assert.equal(result.status, "FAIL");
  assert.equal(result.failure_code, "BrowserFetchFailed");
  assert.equal(result.observations.stage, "launch");
});

test("S11 public evidence strips runtime identifiers and rejects secrets", () => {
  const publicEvidence = publicP8DemoS11PlaywrightEvidence({
    status: "PASS",
    checks: { installed: true },
    runtime: {
      interaction_id: "internal",
      result_projection: { status: "SUCCEEDED" }
    }
  });
  assert.equal("runtime" in publicEvidence, false);
  assert.match(formatP8DemoS11Summary(publicEvidence), /playwright=pass/);
  assert.doesNotThrow(() => assertP8DemoS11EvidenceRedacted(
    {
      status: "PASS",
      runtime: { interaction_id: "recovery-interaction-id" }
    },
    {
      NEX_P8_DEMO_S11_RECOVERY_INTERACTION_ID: "recovery-interaction-id"
    }
  ));
  assert.throws(
    () => assertP8DemoS11EvidenceRedacted(
      { status: "PASS", leaked: "demo-password-value" },
      {
        NEX_P8_DEMO_S11_WEB_URL: "https://ae.nex-staging.test:8443",
        NEX_P8_DEMO_S11_TENANT_ID: "VO00",
        NEX_P8_DEMO_S11_REQUESTER_EMPLOYEE_ID: "1001",
        NEX_P8_DEMO_S11_REQUESTER_PASSWORD: "demo-password-value",
        NEX_P8_DEMO_S11_APPROVER_EMPLOYEE_ID: "2001",
        NEX_P8_DEMO_S11_APPROVER_PASSWORD: "another-demo-password",
        NEX_P8_DEMO_S11_PROMPT: "protected prompt"
      }
    ),
    /leaked/
  );
});
