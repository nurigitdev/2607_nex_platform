#!/usr/bin/env node
import { pathToFileURL } from "node:url";

import { createAeWebServer } from "./serve.mjs";

export const AE_WEB_APPROVAL_UI_PLAYWRIGHT_SMOKE_SCHEMA_VERSION =
  "ae_web_approval_ui_playwright_smoke.p8.v1";

const FORBIDDEN_FRAGMENTS = [
  "access_" + "token",
  "api_" + "key",
  "database_" + "url",
  "password_" + "hash",
  "protected_" + "request",
  "resume_" + "target_ref",
  "semantic_" + "hash",
  "service_" + "token",
  "source_" + "ref",
  "storage_" + "path",
  "/data/" + "nex-platform"
];

export async function runApprovalUiPlaywrightSmoke({
  importPlaywright = () => import("playwright")
} = {}) {
  const server = createAeWebServer();
  let browser = null;
  try {
    const port = await listen(server);
    const playwright = await importPlaywright();
    browser = await playwright.chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
    await page.goto(`http://127.0.0.1:${port}/`, {
      waitUntil: "domcontentloaded",
      timeout: 25000
    });
    await page.fill("#credential-employee-id", "EMP-APPROVAL-SMOKE");
    await page.fill("#credential-password", "mock-password");
    await page.click("#credential-login-submit-button");
    await page.waitForSelector("#authenticated-shell:not([hidden])");
    await page.click('[data-shell-view="approvals"]');
    await page.waitForSelector('[data-approval-domain="NSL_WRITE"]');

    const initial = await page.evaluate(() => ({
      panelPresent: Boolean(document.querySelector("#approval-panel")),
      domains: [...document.querySelectorAll("[data-approval-domain]")].map(
        node => node.getAttribute("data-approval-domain")
      ),
      pageText: document.querySelector("#approval-panel")?.textContent || ""
    }));

    await selectGate(page, "42000000-0000-4000-8000-000000000001");
    await page.fill("#approval-decision-comment", "Playwright 승인 검토");
    await page.click('[data-approval-decision="APPROVE"]');
    await waitForPhase(page, "DECIDED");
    const approve = await decisionObservation(page);

    const duplicate = await page.evaluate(async () => {
      const module = await import(
        new URL("/src/approvalClient.js", globalThis.location.href).href
      );
      const client = module.createMockApprovalClient({
        now: () => new Date("2026-10-22T09:00:00Z")
      });
      const request = module.buildApprovalDecisionRequest({ decision: "APPROVE" });
      const first = await client.submitApprovalDecision(
        "42000000-0000-4000-8000-000000000001",
        request
      );
      const second = await client.submitApprovalDecision(
        "42000000-0000-4000-8000-000000000001",
        request
      );
      return {
        sameDecision: first.decision_id === second.decision_id,
        callCount: client.getDecisionCallCount()
      };
    });

    await selectGate(page, "42000000-0000-4000-8000-000000000003");
    await page.click('[data-approval-decision="REJECT"]');
    await waitForPhase(page, "DECIDED");
    const reject = await decisionObservation(page);

    await selectGate(page, "42000000-0000-4000-8000-000000000002");
    await page.click('[data-approval-decision="APPROVE"]');
    await waitForPhase(page, "UNAUTHORIZED");
    const unauthorized = await decisionObservation(page);

    await page.click(
      '[data-approval-gate-id="42000000-0000-4000-8000-000000000004"]'
    );
    await waitForPhase(page, "EXPIRED");
    const expired = await decisionObservation(page);
    const html = await page.locator("#approval-panel").innerHTML();

    const checks = {
      playwright_browser_launched: true,
      approval_panel_present: initial.panelPresent,
      pending_list_rendered: initial.domains.length === 4,
      domains_preserved:
        new Set(initial.domains).size === 3 &&
        initial.domains.includes("NSL_WRITE") &&
        initial.domains.includes("AGENT_FORMAL") &&
        initial.domains.includes("BUSINESS_FORMAL"),
      detail_loaded: approve.detailPresent,
      approve_recorded:
        approve.phase === "DECIDED" && approve.feedback.includes("승인"),
      reject_recorded:
        reject.phase === "DECIDED" && reject.feedback.includes("반려"),
      unauthorized_action_denied:
        unauthorized.phase === "UNAUTHORIZED" &&
        unauthorized.feedback.includes("권한"),
      expired_item_blocked:
        expired.phase === "EXPIRED" && expired.disabledDecisionCount === 2,
      duplicate_submit_idempotent:
        duplicate.sameDecision === true && duplicate.callCount === 2,
      terminal_actions_disabled: approve.disabledDecisionCount === 2,
      protected_payload_absent: FORBIDDEN_FRAGMENTS.every(
        fragment => !html.toLowerCase().includes(fragment.toLowerCase())
      )
    };
    const evidence = {
      smoke_schema_version:
        AE_WEB_APPROVAL_UI_PLAYWRIGHT_SMOKE_SCHEMA_VERSION,
      status: Object.values(checks).every(Boolean) ? "PASS" : "FAIL",
      runner: {
        tool: "Playwright",
        browser: "chromium",
        headless: true,
        live_network_used: false,
        postgresql_used: false,
        client_mode: "mock"
      },
      observations: {
        gate_count: initial.domains.length,
        domain_count: new Set(initial.domains).size,
        duplicate_call_count: duplicate.callCount,
        final_phase: expired.phase
      },
      checks
    };
    assertApprovalUiEvidenceRedacted(evidence);
    return evidence;
  } finally {
    if (browser) await browser.close();
    await close(server);
  }
}

export function formatSummary(evidence) {
  if (evidence.status !== "PASS") {
    return "ae_web_approval_ui_playwright_smoke=fail reason=checks_failed";
  }
  return (
    "ae_web_approval_ui_playwright_smoke=pass " +
    `gates=${evidence.observations.gate_count} ` +
    `domains=${evidence.observations.domain_count} ` +
    `checks=${Object.keys(evidence.checks).length}`
  );
}

export function assertApprovalUiEvidenceRedacted(evidence) {
  const serialized = JSON.stringify(evidence).toLowerCase();
  for (const fragment of FORBIDDEN_FRAGMENTS) {
    if (serialized.includes(fragment.toLowerCase())) {
      throw new Error("Approval UI evidence leaked protected material");
    }
  }
}

async function selectGate(page, gateId) {
  await page.click(`[data-approval-gate-id="${gateId}"]`);
  await waitForPhase(page, "DETAIL_READY");
}

async function waitForPhase(page, phase) {
  await page.waitForSelector(`.approval-feedback[data-phase="${phase}"]`, {
    timeout: 10000
  });
}

async function decisionObservation(page) {
  return page.evaluate(() => ({
    phase: document.querySelector(".approval-feedback")?.dataset.phase || null,
    feedback: document.querySelector(".approval-feedback")?.textContent?.trim() || "",
    detailPresent: Boolean(document.querySelector(".approval-detail-surface h3")),
    disabledDecisionCount: document.querySelectorAll(
      "[data-approval-decision][disabled]"
    ).length
  }));
}

function listen(server) {
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      server.off("error", reject);
      resolve(server.address().port);
    });
  });
}

function close(server) {
  if (!server.listening) return Promise.resolve();
  return new Promise((resolve, reject) => {
    server.close(error => (error ? reject(error) : resolve()));
  });
}

export async function main(argv = process.argv.slice(2), output = console.log) {
  try {
    const evidence = await runApprovalUiPlaywrightSmoke();
    output(
      argv.includes("--summary")
        ? formatSummary(evidence)
        : JSON.stringify(evidence, null, 2)
    );
    return evidence.status === "PASS" ? 0 : 1;
  } catch (error) {
    output(
      "ae_web_approval_ui_playwright_smoke=fail " +
        `error=${error?.constructor?.name || "Error"}`
    );
    return 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await main();
}
