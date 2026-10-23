#!/usr/bin/env node
import { pathToFileURL } from "node:url";

import { createAeWebServer } from "./serve.mjs";

export const AE_WEB_VOUCHER_ATTACHMENT_PLAYWRIGHT_SCHEMA_VERSION =
  "ae_web_voucher_attachment_playwright.p8.v1";

const FORBIDDEN_FRAGMENTS = [
  "access_" + "token",
  "api_" + "key",
  "bucket_" + "name",
  "database_" + "url",
  "object_" + "key",
  "password_" + "hash",
  "service_" + "token",
  "storage_" + "path",
  "/data/" + "nex-platform"
];

export async function runVoucherAttachmentPlaywrightSmoke({
  importPlaywright = () => import("playwright")
} = {}) {
  const server = createAeWebServer();
  let browser = null;
  let stage = "server_start";
  const pageErrors = [];
  try {
    const port = await listen(server);
    stage = "browser_launch";
    const playwright = await importPlaywright();
    browser = await playwright.chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
    page.on("pageerror", error => pageErrors.push(error?.name || "Error"));
    stage = "anonymous_surface";
    await page.goto(`http://127.0.0.1:${port}/`, {
      waitUntil: "domcontentloaded",
      timeout: 25000
    });

    const anonymousComposerHidden = await page.isHidden("#voucher-attachment-ui");
    stage = "login";
    await page.fill("#credential-employee-id", "EMP-P8-S75G");
    await page.fill("#credential-password", "mock-password");
    await page.click("#credential-login-submit-button");
    await page.waitForSelector("#authenticated-shell:not([hidden])");

    stage = "multiple_upload";
    await page.setInputFiles("[data-voucher-attachment-input]", [
      {
        name: "교통비-영수증.png",
        mimeType: "image/png",
        buffer: Buffer.from("p8-s75g-image")
      },
      {
        name: "출장비-내역.pdf",
        mimeType: "application/pdf",
        buffer: Buffer.from("p8-s75g-pdf")
      },
      {
        name: "증빙-묶음.zip",
        mimeType: "application/zip",
        buffer: Buffer.from("p8-s75g-zip")
      }
    ]);
    await page.waitForSelector(
      '[data-voucher-attachment-phase="READY"] [data-state="READY"]'
    );
    const ready = await composerObservation(page);

    stage = "manifest_lock";
    await page.fill("#prompt", "첨부한 증빙으로 출장비 전표를 작성해줘.");
    await page.click("#composer button[type='submit']");
    await page.waitForSelector('[data-voucher-attachment-phase="LOCKED"]');
    const locked = await composerObservation(page);
    if (locked.phase !== "LOCKED") {
      return {
        smoke_schema_version: AE_WEB_VOUCHER_ATTACHMENT_PLAYWRIGHT_SCHEMA_VERSION,
        status: "FAIL",
        failure_code: "manifest_lock_failed",
        observations: {
          stage,
          composer_phase: locked.phase,
          composer_feedback: locked.feedback
        },
        checks: {}
      };
    }

    stage = "approval_review";
    await page.click('[data-shell-view="approvals"]');
    await page.waitForSelector('[data-approval-domain="NSL_WRITE"]');
    await page.click(
      '[data-approval-gate-id="42000000-0000-4000-8000-000000000001"]'
    );
    await page.waitForSelector('[data-approval-attachment-manifest="true"]');
    const review = await page.evaluate(() => ({
      count: Number(
        document
          .querySelector("[data-approval-attachment-manifest]")
          ?.getAttribute("data-attachment-count") || 0
      ),
      links: document.querySelectorAll(".approval-attachment-actions a").length,
      text: document.querySelector(".approval-attachment-manifest")?.textContent || "",
      html: document.querySelector("#approval-panel")?.innerHTML || ""
    }));

    stage = "new_version";
    await page.click('[data-shell-view="workspace"]');
    await page.click("[data-voucher-attachment-new-version]");
    const versionReset = await composerObservation(page);

    stage = "logout";
    await page.click("#credential-logout-button");
    await page.waitForSelector("#authentication-shell:not([hidden])");

    const checks = {
      playwright_browser_launched: true,
      anonymous_attachment_surface_hidden: anonymousComposerHidden,
      multiple_selection_ready:
        ready.itemCount === 3 && ready.readyCount === 3 && ready.phase === "READY",
      approval_submit_locks_manifest:
        locked.itemCount === 3 &&
        locked.lockedCount === 3 &&
        locked.phase === "LOCKED" &&
        locked.selectDisabled,
      safe_review_manifest_visible:
        review.count === 2 &&
        review.links === 4 &&
        review.text.includes("승인 고정 증빙"),
      new_approval_version_required:
        versionReset.phase === "IDLE" &&
        versionReset.itemCount === 0 &&
        versionReset.approvalVersion === "2",
      logout_returns_to_login: await page.isVisible("#credential-login-panel"),
      storage_internals_absent: FORBIDDEN_FRAGMENTS.every(
        fragment => !review.html.toLowerCase().includes(fragment.toLowerCase())
      )
    };
    return {
      smoke_schema_version: AE_WEB_VOUCHER_ATTACHMENT_PLAYWRIGHT_SCHEMA_VERSION,
      status: Object.values(checks).every(Boolean) ? "PASS" : "FAIL",
      runner: {
        tool: "Playwright",
        browser: "chromium",
        headless: true,
        authenticated: true,
        client_mode: "mock"
      },
      observations: {
        selected_file_count: ready.itemCount,
        locked_file_count: locked.lockedCount,
        review_attachment_count: review.count,
        review_link_count: review.links
      },
      checks
    };
  } catch (error) {
    return {
      smoke_schema_version: AE_WEB_VOUCHER_ATTACHMENT_PLAYWRIGHT_SCHEMA_VERSION,
      status: "FAIL",
      failure_code: error?.constructor?.name || "playwright_failed",
      observations: {
        stage,
        page_error_count: pageErrors.length,
        page_error_names: pageErrors.slice(-3),
        error_message: String(error?.message || "").slice(0, 240)
      },
      checks: {}
    };
  } finally {
    if (browser) await browser.close();
    await close(server);
  }
}

export function formatVoucherAttachmentSummary(evidence) {
  if (evidence.status !== "PASS") {
    return "p8_s75g_voucher_attachment_playwright=fail reason=checks_failed";
  }
  return (
    "p8_s75g_voucher_attachment_playwright=pass " +
    `selected=${evidence.observations.selected_file_count} ` +
    `locked=${evidence.observations.locked_file_count} ` +
    `checks=${Object.keys(evidence.checks).length}`
  );
}

async function composerObservation(page) {
  return page.evaluate(() => {
    const composer = document.querySelector("[data-voucher-attachment-phase]");
    const version = document.querySelector(".voucher-attachment-version")?.textContent || "";
    return {
      phase: composer?.getAttribute("data-voucher-attachment-phase"),
      itemCount: document.querySelectorAll("[data-voucher-attachment-item]").length,
      readyCount: document.querySelectorAll('[data-voucher-attachment-item][data-state="READY"]').length,
      lockedCount: document.querySelectorAll('[data-voucher-attachment-item][data-state="LOCKED"]').length,
      selectDisabled: Boolean(
        document.querySelector("[data-voucher-attachment-select]")?.disabled
      ),
      approvalVersion: version.match(/\d+/)?.[0] || null,
      feedback:
        document.querySelector(".voucher-attachment-feedback")?.textContent?.trim() || ""
    };
  });
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
    const evidence = await runVoucherAttachmentPlaywrightSmoke();
    output(
      argv.includes("--summary")
        ? formatVoucherAttachmentSummary(evidence)
        : JSON.stringify(evidence, null, 2)
    );
    return evidence.status === "PASS" ? 0 : 1;
  } catch (error) {
    output(
      "p8_s75g_voucher_attachment_playwright=fail " +
        `error=${error?.constructor?.name || "Error"}`
    );
    return 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await main();
}
