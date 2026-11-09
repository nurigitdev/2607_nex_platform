#!/usr/bin/env node
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { chromium } from "@playwright/test";
import { createServer } from "vite";

import { evaluateUxAcceptanceV2Page } from "./uxAcceptanceV2Browser.mjs";

export const MODERN_ARTIFACT_SMOKE_SCHEMA_VERSION = "ae_web_modern_artifact_smoke.uxm_s16.v1";
const APP_ROOT = fileURLToPath(new URL("..", import.meta.url));
const DEFAULT_EVIDENCE_DIR = resolve(APP_ROOT, "../../reports/uiux/artifact-modernization");

export async function runModernArtifactPlaywrightSmoke({ evidenceDir = DEFAULT_EVIDENCE_DIR } = {}) {
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
    const requests = [];
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    context.on("request", request => {
      const url = new URL(request.url());
      if (url.pathname.startsWith("/ae-api")) requests.push({ method: request.method(), origin: url.origin, path: url.pathname });
    });
    await context.route("**/ae-api/**", async route => {
      const request = route.request();
      const path = new URL(request.url()).pathname.slice("/ae-api".length);
      if (path.endsWith("/session") && request.method() === "GET") return json(route, 401, {});
      if (path.endsWith("/session/login") && request.method() === "POST") return json(route, 200, activeSession(request.postDataJSON()));
      if (path === "/api/v1/workspaces" && request.method() === "POST") return json(route, 200, workspaceResponse());
      if (path === "/api/v1/artifacts" && request.method() === "GET") return json(route, 200, artifactCollection());
      if (path === "/api/v1/artifacts/artifact-uxm-s16" && request.method() === "GET") return json(route, 200, artifactRecord());
      if (path === "/api/v1/artifacts/artifact-uxm-s16/versions" && request.method() === "GET") return json(route, 200, versionsPayload());
      if (path === "/api/v1/artifact-files/file-uxm-s16/preview" && request.method() === "GET") return json(route, 200, previewPayload());
      if (path === "/api/v1/artifact-files/file-uxm-s16/download" && request.method() === "GET") return json(route, 200, downloadPayload());
      if (path === "/api/v1/artifacts/artifact-uxm-s16/render-jobs" && request.method() === "POST") return json(route, 200, renderPayload());
      if (path === "/api/v1/artifacts/artifact-uxm-s16/lifecycle-actions" && request.method() === "POST") return json(route, 200, lifecyclePayload(request.postDataJSON(), request.headers()["idempotency-key"]));
      return json(route, 404, {});
    });

    await mkdir(evidenceDir, { recursive: true });
    const page = await context.newPage();
    await page.goto(`${origin}/modern.html`, { waitUntil: "networkidle" });
    await page.getByLabel(/^사번\s*\*?$/).fill("EMP-UXM-S16");
    await page.getByLabel(/^비밀번호\s*\*?$/).fill("protected-smoke-password");
    await page.getByRole("button", { name: "로그인" }).click();
    await page.getByRole("link", { name: "결과물" }).click();
    await page.getByRole("heading", { name: "결과물", exact: true }).waitFor();
    await page.getByRole("button", { name: /NVT 프로젝트 정산 보고서/ }).click();
    await page.getByRole("heading", { name: "버전" }).waitFor();
    await page.getByRole("button", { name: "미리보기" }).click();
    await page.getByText("승인된 교통비 정산 결과입니다.").waitFor();
    const previewObserved = await page.getByText("승인된 교통비 정산 결과입니다.").isVisible();
    await page.getByRole("button", { name: "PDF 만들기" }).click();
    await page.getByText("PDF 파일 생성을 요청했습니다.").waitFor();
    await page.getByRole("button", { name: "다운로드" }).click();
    await page.getByText("nvt-settlement.md 다운로드를 시작했습니다.").waitFor();
    await page.getByRole("button", { name: "보관" }).click();
    await page.getByText("결과물을 보관했습니다.").waitFor();
    await page.screenshot({ path: resolve(evidenceDir, "01-artifact-desktop.png"), fullPage: true });
    const desktop = await snapshot(page);
    const desktopAcceptance = await evaluateUxAcceptanceV2Page(page, {
      profile: "application",
      viewport: "desktop",
      requestUrls: requests.map(item => `${item.origin}${item.path}`),
    });

    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: resolve(evidenceDir, "02-artifact-mobile.png"), fullPage: true });
    const mobile = await snapshot(page);
    const mobileAcceptance = await evaluateUxAcceptanceV2Page(page, {
      profile: "application",
      viewport: "mobile",
      requestUrls: requests.map(item => `${item.origin}${item.path}`),
    });
    const checks = {
      detail_loaded: requests.some(item => item.path === "/ae-api/api/v1/artifacts/artifact-uxm-s16"),
      preview_loaded: previewObserved,
      download_called: requests.some(item => item.path.endsWith("/artifact-files/file-uxm-s16/download")),
      export_called: requests.some(item => item.path.endsWith("/artifacts/artifact-uxm-s16/render-jobs")),
      lifecycle_called: requests.some(item => item.path.endsWith("/artifacts/artifact-uxm-s16/lifecycle-actions")),
      safe_business_copy: desktop.body.includes("결과물") && !desktop.body.includes("Artifact"),
      no_private_leak: !/storage_ref|ae:\/\/|service_token|provider_endpoint|\/data\//i.test(desktop.body),
      desktop_no_overflow: !desktop.overflow,
      mobile_no_overflow: !mobile.overflow,
      same_origin: requests.every(item => item.origin === origin && item.path.startsWith("/ae-api/")),
      desktop_acceptance_v2: desktopAcceptance.status === "PASS",
      mobile_acceptance_v2: mobileAcceptance.status === "PASS",
    };
    return {
      schema_version: MODERN_ARTIFACT_SMOKE_SCHEMA_VERSION,
      status: Object.values(checks).every(Boolean) ? "PASS" : "FAIL",
      checks,
      observations: { request_count: requests.length, screenshot_count: 2, acceptance_v2: { desktop: desktopAcceptance, mobile: mobileAcceptance } },
    };
  } finally {
    if (browser) await browser.close();
    await server.close();
  }
}

function activeSession(input) {
  return {
    browser_session_schema_version: "oa_browser_session.v1", session_id: "session-uxm-s16", status: "ACTIVE",
    issuer: "nex-oa", audience: "nex-ae-api", token_use: "user",
    tenant_ref: { type: "oa.tenant", id: input.tenant_id }, subject_ref: { type: "oa.user", id: "subject-uxm-s16" },
    scopes: input.requested_scopes, roles: ["employee"], issued_at: "2026-11-09T00:00:00Z", expires_at: "2026-11-09T01:00:00Z",
    metadata: { raw_token_included: false, service_token_included: false, password_included: false, browser_payload_owner_authoritative: false, claim_owner_authoritative: true },
  };
}

function workspaceResponse() {
  return { workspace_schema_version: "ae_workspace_state.v1", workspace_id: "workspace-uxm-s16", chat_document_id: "conversation-uxm-s16", title: "내 업무 공간" };
}

function artifactRecord() {
  return {
    artifact_schema_version: "ae_artifact_record.v1", artifact_id: "artifact-uxm-s16", artifact_type: "generated_document", artifact_status: "READY",
    current_version_id: "version-uxm-s16-2", chat_document_id: "chat-uxm-s16", interaction_id: "interaction-uxm-s16",
    display_title: "NVT 프로젝트 정산 보고서", language: "ko", artifact_intent: "create_and_export", target_formats: ["MD", "PDF"],
    owner_actor_ref: { actor_type: "user", actor_id: "subject-uxm-s16", tenant_id: "tenant-uxm-s16" }, workspace_ref: { workspace_id: "workspace-uxm-s16", workspace_name: "내 업무 공간" },
    source_refs: [{ cx_generation_id: "generation-uxm-s16", structured_draft_id: "draft-uxm-s16", structured_draft_content_hash: "c".repeat(64), retrieval_package_id: "retrieval-uxm-s16", retrieval_package_hash: "r".repeat(64), evidence_ref_count: 3, source_anchor_count: 3, quality_summary: { citation_status: "VALIDATED", citation_count: 3, validation_error_count: 0, warning_count: 0, grounding_required: true, retrieval_package_id: "retrieval-uxm-s16", evidence_ref_count: 3 } }],
    versions: [version(1, "version-uxm-s16-1", ["MD"]), version(2, "version-uxm-s16-2", ["MD", "PDF"])],
    files: [artifactFile()], links: artifactLinks(),
    render_jobs: [{ render_job_id: "render-uxm-s16", job_status: "COMPLETED", current_stage: "FINALIZING", progress_percent: 100, retryable: false, failure_code: null }],
    created_at: "2026-11-09T00:00:00Z", updated_at: "2026-11-09T00:10:00Z",
  };
}

function artifactCollection() {
  return {
    artifact_collection_schema_version: "ae_artifact_collection.v1",
    filter: { tenant_id: "tenant-uxm-s16", workspace_id: "workspace-uxm-s16", owner_user_id: "subject-uxm-s16", status: null, limit: 50 }, count: 1, limit: 50, next_cursor: null,
    items: [{
      artifact_collection_item_schema_version: "ae_artifact_collection_item.v1", artifact_id: "artifact-uxm-s16", artifact_type: "generated_document", artifact_status: "READY", display_title: "NVT 프로젝트 정산 보고서", language: "ko", artifact_intent: "create_and_export",
      target_formats: ["MD", "PDF"], available_formats: ["MD", "PDF"], downloadable_formats: ["MD", "PDF"], previewable_formats: ["MD"], current_version_id: "version-uxm-s16-2", current_version_no: 2, version_count: 2, file_count: 1, link_count: 2, render_job_count: 1,
      latest_render_job: { render_job_id: "render-uxm-s16", job_status: "COMPLETED", current_stage: "FINALIZING", progress_percent: 100, retryable: false, failure_code: null },
      source_summary: { cx_generation_id: "generation-uxm-s16", structured_draft_id: "draft-uxm-s16", retrieval_package_id: "retrieval-uxm-s16", retrieval_package_hash: "r".repeat(64), evidence_ref_count: 3, source_anchor_count: 3 },
      quality_summary: { citation_status: "VALIDATED", citation_count: 3, validation_error_count: 0, warning_count: 0, grounding_required: true, evidence_ref_count: 3 },
      routes: { detail: "/api/v1/artifacts/artifact-uxm-s16", versions: "/api/v1/artifacts/artifact-uxm-s16/versions" }, tenant_id: "tenant-uxm-s16", workspace_id: "workspace-uxm-s16", owner_user_id: "subject-uxm-s16", chat_document_id: "chat-uxm-s16", interaction_id: "interaction-uxm-s16", created_at: "2026-11-09T00:00:00Z", updated_at: "2026-11-09T00:10:00Z",
    }],
  };
}

function version(number, id, formats) {
  return { artifact_version_id: id, version_no: number, source_content_hash: "c".repeat(64), artifact_content_hash: "e".repeat(64), rendered_formats: formats };
}

function artifactFile() {
  return { artifact_file_id: "file-uxm-s16", artifact_id: "artifact-uxm-s16", artifact_version_id: "version-uxm-s16-2", format: "MD", mime_type: "text/markdown", file_name: "nvt-settlement.md", storage_ref: "ae://private/artifact-uxm-s16/nvt-settlement.md", file_size_bytes: 512, file_hash: "f".repeat(64), source_version_hash: "e".repeat(64) };
}

function artifactLinks() {
  return [
    { artifact_link_id: "preview-uxm-s16", artifact_file_id: "file-uxm-s16", link_type: "preview", access_policy: "owner_only", link_route: "/api/v1/artifact-files/file-uxm-s16/preview" },
    { artifact_link_id: "download-uxm-s16", artifact_file_id: "file-uxm-s16", link_type: "download", access_policy: "owner_only", link_route: "/api/v1/artifact-files/file-uxm-s16/download" },
  ];
}

function versionsPayload() {
  return { artifact_id: "artifact-uxm-s16", current_version_id: "version-uxm-s16-2", versions: [version(1, "version-uxm-s16-1", ["MD"]), version(2, "version-uxm-s16-2", ["MD", "PDF"])] };
}

function previewPayload() {
  return { preview_schema_version: "ae_artifact_file_preview.v1", artifact_file: artifactFile(), artifact_link: artifactLinks()[0], content_type: "text/markdown", text_preview: "# 정산 결과\n\n승인된 교통비 정산 결과입니다.", truncated: false };
}

function downloadPayload() {
  return { download_schema_version: "ae_artifact_file_download.v1", artifact_file: artifactFile(), artifact_link: artifactLinks()[1], download_file_name: "nvt-settlement.md", content_type: "text/markdown", content_hash: "f".repeat(64), content: "# 정산 결과" };
}

function renderPayload() {
  return { render_result_schema_version: "ae_markdown_render_result.v1", render_job: { render_job_id: "render-uxm-s16-2", job_status: "COMPLETED", current_stage: "FINALIZING", progress_percent: 100 }, artifact: artifactRecord() };
}

function lifecyclePayload(input, idempotencyKey) {
  return {
    artifact_lifecycle_action_result_schema_version: "ae_artifact_lifecycle_action_result.v1",
    lifecycle_action: { artifact_lifecycle_action_schema_version: "ae_artifact_lifecycle_action.v1", lifecycle_action_id: "action-uxm-s16", artifact_id: "artifact-uxm-s16", action: input.action, previous_status: "READY", target_status: "ARCHIVED", restore_status: null, reason_code: "user_requested", comment_hash: null, comment_length: 0, actor_ref: { actor_type: "user", actor_id: "subject-uxm-s16", tenant_id: "tenant-uxm-s16" }, request_id: "request-uxm-s16", trace_id: "0".repeat(32), idempotency_key: idempotencyKey, metadata: { physical_delete_requested: false, storage_mutation_requested: false, raw_comment_included: false } },
    artifact_id: "artifact-uxm-s16", artifact_status: "ARCHIVED", previous_status: "READY", target_status: "ARCHIVED", transition_applied: true,
    routes: { artifact: "/api/v1/artifacts/artifact-uxm-s16", collection: "/api/v1/artifacts" }, updated_at: "2026-11-09T00:20:00Z", metadata: { rendered_payload_included: false, storage_location_included: false, physical_delete_executed: false },
  };
}

async function snapshot(page) {
  return page.evaluate(() => ({ body: document.body.innerText, overflow: document.documentElement.scrollWidth > window.innerWidth + 1 }));
}

async function json(route, status, body) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

export function formatSummary(evidence) {
  return evidence.status === "PASS"
    ? `modern_artifact_playwright_smoke=pass requests=${evidence.observations.request_count} screenshots=${evidence.observations.screenshot_count} checks=${Object.keys(evidence.checks).length}`
    : "modern_artifact_playwright_smoke=fail reason=checks_failed";
}

export async function main(argv = process.argv.slice(2), output = console.log) {
  try {
    const evidence = await runModernArtifactPlaywrightSmoke();
    output(argv.includes("--summary") ? formatSummary(evidence) : JSON.stringify(evidence, null, 2));
    return evidence.status === "PASS" ? 0 : 1;
  } catch (error) {
    output(`modern_artifact_playwright_smoke=fail error=${error?.constructor?.name ?? "Error"}`);
    return 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) process.exitCode = await main();
