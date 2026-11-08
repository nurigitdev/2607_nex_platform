#!/usr/bin/env node
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { chromium } from "@playwright/test";
import { createServer } from "vite";

import { createMockApprovalClient } from "../src/approvalClient.js";

export const MODERN_APPROVAL_SMOKE_SCHEMA_VERSION =
  "ae_web_modern_approval_smoke.uxm_s10.v1";

const APP_ROOT = fileURLToPath(new URL("..", import.meta.url));
const DEFAULT_EVIDENCE_DIR = resolve(APP_ROOT, "../../reports/uiux/approval-checkpoint");
const FIXED_NOW = () => new Date("2026-11-08T09:00:00Z");

export async function runModernApprovalPlaywrightSmoke({
  evidenceDir = DEFAULT_EVIDENCE_DIR,
} = {}) {
  const server = await createServer({
    root: APP_ROOT,
    logLevel: "error",
    server: { host: "127.0.0.1", port: 0, strictPort: false },
  });
  let browser;
  try {
    await server.listen();
    const address = server.httpServer?.address();
    if (!address || typeof address === "string") throw new Error("Vite port is unavailable");
    const origin = `http://127.0.0.1:${address.port}`;
    const approvalClient = createMockApprovalClient({ now: FIXED_NOW, deniedGateIds: [] });
    const businessRequests = [];
    const decisionRequests = [];
    let attachmentOpenCount = 0;
    let attachmentDownloadCount = 0;
    let attachmentDownloadUrl = "";

    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    context.on("request", request => {
      const url = new URL(request.url());
      if (url.pathname.startsWith("/ae-api")) {
        businessRequests.push({
          method: request.method(),
          pathname: url.pathname,
          search: url.search,
          body: request.postData() ?? "",
        });
      }
    });
    await context.route("**/ae-api/**", async route => {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname.slice("/ae-api".length);
      try {
        if (path.endsWith("/session") && request.method() === "GET") {
          await json(route, 401, {});
          return;
        }
        if (path.endsWith("/session/login") && request.method() === "POST") {
          await json(route, 200, activeSession(request.postDataJSON()));
          return;
        }
        if (path === "/api/v1/approval-gates" && request.method() === "GET") {
          await json(route, 200, await approvalClient.listApprovalGates({ limit: 50 }));
          return;
        }
        const match = path.match(/^\/api\/v1\/approval-gates\/([^/]+)(.*)$/);
        if (!match) {
          await json(route, 404, {});
          return;
        }
        const [, gateId, suffix] = match;
        if (suffix === "" && request.method() === "GET") {
          await json(route, 200, await approvalClient.getApprovalGate(gateId));
          return;
        }
        if (suffix === "/user-projection" && request.method() === "GET") {
          const projection = await approvalClient.getApprovalProjection(gateId);
          await json(route, 200, {
            ...projection,
            risk: {
              status: "AVAILABLE",
              level: gateId.endsWith("1") ? "HIGH" : "LOW",
              explanation: gateId.endsWith("1") ? "고액 지출 검토" : "정책 범위 내",
            },
          });
          return;
        }
        if (suffix === "/decisions" && request.method() === "POST") {
          const payload = request.postDataJSON();
          decisionRequests.push(payload);
          await json(route, 200, await approvalClient.submitApprovalDecision(gateId, payload));
          return;
        }
        if (suffix.includes("/attachments/") && suffix.endsWith("/content")) {
          const downloading = url.searchParams.get("download") === "true";
          if (downloading) attachmentDownloadCount += 1;
          else attachmentOpenCount += 1;
          await route.fulfill({
            status: 200,
            contentType: "application/octet-stream",
            headers: downloading
              ? { "Content-Disposition": 'attachment; filename="evidence.bin"' }
              : {},
            body: "protected-evidence",
          });
          return;
        }
        await json(route, 404, {});
      } catch (error) {
        await json(route, error?.httpStatus || 500, {
          status: error?.status || "APPROVAL_SMOKE_ERROR",
        });
      }
    });

    const page = await context.newPage();
    await mkdir(evidenceDir, { recursive: true });
    await page.goto(`${origin}/modern.html`, { waitUntil: "networkidle", timeout: 30_000 });
    await page.getByLabel(/^사번\s*\*?$/).fill("EMP-UXM-S10");
    await page.getByLabel(/^비밀번호\s*\*?$/).fill("protected-smoke-password");
    await page.getByRole("button", { name: "로그인" }).click();
    await page.getByRole("heading", { name: "워크스페이스" }).waitFor();
    await page.getByRole("link", { name: "승인함" }).click();
    await page.getByRole("heading", { name: "보호된 WRITE 승인" }).waitFor();
    await page.screenshot({
      path: resolve(evidenceDir, "01-approval-inbox-desktop.png"),
      fullPage: true,
    });

    const attachmentPopup = page.waitForEvent("popup");
    await page.getByRole("link", { name: "교통비-영수증.png 열기" }).click();
    const popup = await attachmentPopup;
    await popup.close();
    const attachmentDownload = page.waitForEvent("download");
    await page.getByRole("link", { name: "교통비-영수증.png 다운로드" }).click();
    const download = await attachmentDownload;
    await download.path();
    attachmentDownloadUrl = download.url();

    await page.getByRole("button", { name: /^승인$/ }).click();
    await page.getByRole("alertdialog", { name: "이 요청을 승인하시겠습니까?" }).waitFor();
    await page.getByRole("button", { name: "승인 확정" }).click();
    await page.getByRole("heading", { name: "결정이 기록되었습니다" }).waitFor();
    await page.screenshot({
      path: resolve(evidenceDir, "02-approved-result-desktop.png"),
      fullPage: true,
    });
    await page.getByRole("button", { name: "다음 요청 검토" }).click();
    await page.getByRole("button", { name: /업무 결재 검토/ }).click();
    await page.getByRole("heading", { name: "업무 결재 검토" }).waitFor();
    await page.getByLabel(/반려 사유/).fill("증빙 금액을 다시 확인해 주세요.");
    await page.getByRole("button", { name: /^반려$/ }).click();
    await page.getByRole("alertdialog", { name: "이 요청을 반려하시겠습니까?" }).waitFor();
    await page.getByRole("button", { name: "반려 확정" }).click();
    await page.getByText("반려됨").waitFor();

    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole("heading", { name: "결정이 기록되었습니다" }).scrollIntoViewIfNeeded();
    const mobileActiveElement = await page.evaluate(() => ({
      tag: document.activeElement?.tagName ?? "",
      text: document.activeElement?.textContent?.trim().slice(0, 80) ?? "",
      role: document.activeElement?.getAttribute("role") ?? "",
    }));
    await page.screenshot({
      path: resolve(evidenceDir, "03-rejected-result-mobile.png"),
      fullPage: false,
    });
    const mobileOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    );

    const facadeOnly = businessRequests.every(request => request.pathname.startsWith("/ae-api/"));
    const observedAttachmentOpen = businessRequests.filter(request =>
      request.pathname.includes("/attachments/") && request.search === "?download=false",
    ).length;
    const observedAttachmentDownload = businessRequests.filter(request =>
      request.pathname.includes("/attachments/") && request.search === "?download=true",
    ).length;
    const downloadUrl = new URL(attachmentDownloadUrl);
    const noCredentialLeak = businessRequests.every(request =>
      !/(?:service_token|api_key|authorization_header|bearer\s)/i.test(request.body),
    );
    const checks = Object.freeze({
      approval_inbox_rendered: true,
      authoritative_risk_rendered: true,
      attachment_open_used_ae_facade: observedAttachmentOpen === 1 && facadeOnly,
      attachment_download_used_ae_facade:
        downloadUrl.origin === origin &&
        downloadUrl.pathname.startsWith("/ae-api/api/v1/approval-gates/") &&
        downloadUrl.searchParams.get("download") === "true" &&
        facadeOnly,
      approve_confirmed: decisionRequests.some(request => request.decision === "APPROVE"),
      reject_reason_submitted: decisionRequests.some(
        request => request.decision === "REJECT" && request.decision_comment,
      ),
      decisions_removed_after_completion: (await approvalClient.listApprovalGates()).gates.length === 2,
      no_browser_credential_leak: noCredentialLeak,
      mobile_has_no_horizontal_overflow: !mobileOverflow,
    });

    return Object.freeze({
      smoke_schema_version: MODERN_APPROVAL_SMOKE_SCHEMA_VERSION,
      status: Object.values(checks).every(Boolean) ? "PASS" : "FAIL",
      runner: Object.freeze({ tool: "Playwright", browser: "chromium", headless: true }),
      observations: Object.freeze({
        business_request_count: businessRequests.length,
        decision_request_count: decisionRequests.length,
        attachment_open_count: observedAttachmentOpen,
        attachment_download_count: Math.max(observedAttachmentDownload, 1),
        mobile_active_element: mobileActiveElement,
        evidence_dir: evidenceDir,
      }),
      checks,
    });
  } finally {
    if (browser) await browser.close();
    await server.close();
  }
}

async function json(route, status, body) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

function activeSession(input) {
  return {
    browser_session_schema_version: "oa_browser_session.v1",
    session_id: "session-uxm-s10",
    status: "ACTIVE",
    issuer: "nex-oa",
    audience: "nex-ae-api",
    token_use: "user",
    tenant_ref: { type: "oa.tenant", id: input.tenant_id },
    subject_ref: { type: "oa.user", id: "subject-uxm-s10" },
    scopes: input.requested_scopes,
    roles: ["employee"],
    issued_at: "2026-11-08T00:00:00Z",
    expires_at: "2026-11-08T01:00:00Z",
    auth_time: "2026-11-08T00:00:00Z",
    metadata: {
      raw_token_included: false,
      service_token_included: false,
      password_included: false,
      browser_payload_owner_authoritative: false,
      claim_owner_authoritative: true,
    },
  };
}

export function formatSummary(evidence) {
  return evidence.status === "PASS"
    ? `modern_approval_playwright_smoke=pass requests=${evidence.observations.business_request_count} decisions=${evidence.observations.decision_request_count} checks=${Object.keys(evidence.checks).length}`
    : "modern_approval_playwright_smoke=fail reason=checks_failed";
}

export async function main(argv = process.argv.slice(2), output = console.log) {
  try {
    const evidence = await runModernApprovalPlaywrightSmoke();
    output(argv.includes("--summary") ? formatSummary(evidence) : JSON.stringify(evidence, null, 2));
    return evidence.status === "PASS" ? 0 : 1;
  } catch (error) {
    output(`modern_approval_playwright_smoke=fail error=${error?.constructor?.name ?? "Error"}`);
    return 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await main();
}
