#!/usr/bin/env node
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { chromium } from "@playwright/test";
import { createServer } from "vite";

export const MODERN_DOCUMENT_SMOKE_SCHEMA_VERSION = "ae_web_modern_document_smoke.uxm_s15.v1";
const APP_ROOT = fileURLToPath(new URL("..", import.meta.url));
const DEFAULT_EVIDENCE_DIR = resolve(APP_ROOT, "../../reports/uiux/document-modernization");

export async function runModernDocumentPlaywrightSmoke({ evidenceDir = DEFAULT_EVIDENCE_DIR } = {}) {
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
    let uploaded = false;
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    context.on("request", request => {
      const url = new URL(request.url());
      if (url.pathname.startsWith("/ae-api")) {
        requests.push({ method: request.method(), origin: url.origin, path: url.pathname });
      }
    });
    await context.route("**/ae-api/**", async route => {
      const request = route.request();
      const path = new URL(request.url()).pathname.slice("/ae-api".length);
      if (path.endsWith("/session") && request.method() === "GET") return json(route, 401, {});
      if (path.endsWith("/session/login") && request.method() === "POST") {
        return json(route, 200, activeSession(request.postDataJSON()));
      }
      if (path === "/api/v1/workspaces" && request.method() === "POST") {
        return json(route, 200, workspaceResponse());
      }
      if (path === "/api/v1/workspaces/workspace-uxm-s15/documents" && request.method() === "GET") {
        return json(route, 200, { workspace_id: "workspace-uxm-s15", documents: uploaded ? [documentItem()] : [] });
      }
      if (path === "/api/v1/uploads/files" && request.method() === "POST") {
        uploaded = true;
        return json(route, 200, uploadHandoff());
      }
      if (path === "/api/v1/uploads/handoff-uxm-s15/progress" && request.method() === "GET") {
        return json(route, 200, uploadProgress());
      }
      if (path === "/api/v1/documents/document-uxm-s15" && request.method() === "GET") {
        return json(route, 200, documentDetail());
      }
      if (path === "/api/v1/retrieval/contexts" && request.method() === "POST") {
        return json(route, 200, retrievalResult());
      }
      return json(route, 404, {});
    });

    await mkdir(evidenceDir, { recursive: true });
    const page = await context.newPage();
    await page.goto(`${origin}/modern.html`, { waitUntil: "networkidle" });
    await page.getByLabel(/^사번\s*\*?$/).fill("EMP-UXM-S15");
    await page.getByLabel(/^비밀번호\s*\*?$/).fill("protected-smoke-password");
    await page.getByRole("button", { name: "로그인" }).click();
    await page.getByRole("link", { name: "문서" }).click();
    await page.getByRole("heading", { name: "문서" }).waitFor();
    await page.getByRole("tab", { name: "파일 첨부" }).click();
    await page.getByLabel("업무에 사용할 파일 선택").setInputFiles({
      name: "receipt.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from("safe browser fixture"),
    });
    await page.getByRole("button", { name: "파일 첨부" }).click();
    await page.getByText("문서 근거로 사용할 수 있습니다.").waitFor();
    await page.getByRole("tab", { name: /내 문서/ }).click();
    await page.getByText("출장비 영수증 요약").waitFor();
    await page.getByRole("button", { name: "상세 보기" }).click();
    await page.getByRole("heading", { name: "문서 상세" }).waitFor();
    await page.screenshot({ path: resolve(evidenceDir, "01-document-desktop.png"), fullPage: true });

    await page.getByRole("tab", { name: "문서 근거 찾기" }).click();
    await page.getByRole("checkbox", { name: "receipt.pdf" }).click();
    await page.getByLabel("찾을 내용").fill("교통비 근거");
    await page.getByRole("button", { name: "근거 찾기" }).click();
    await page.getByRole("heading", { name: "사용한 출처" }).waitFor();
    await page.screenshot({ path: resolve(evidenceDir, "02-retrieval-desktop.png"), fullPage: true });
    const desktop = await snapshot(page);

    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: resolve(evidenceDir, "03-retrieval-mobile.png"), fullPage: true });
    const mobile = await snapshot(page);
    const checks = {
      document_detail: requests.some(item => item.path.endsWith("/documents/document-uxm-s15")),
      retrieval_source: desktop.body.includes("근거 2건을 찾았습니다."),
      owner_private: !desktop.body.includes("tenant-uxm-s15") && !desktop.body.includes("subject-uxm-s15"),
      no_storage_leak: !/source_sha256|provider|127\.0\.0\.1:810\d|\/data\//i.test(desktop.body),
      desktop_no_overflow: !desktop.overflow,
      mobile_no_overflow: !mobile.overflow,
      same_origin: requests.every(item => item.origin === origin && item.path.startsWith("/ae-api/")),
      upload_called: requests.some(item => item.path.endsWith("/uploads/files")),
      retrieval_called: requests.some(item => item.path.endsWith("/retrieval/contexts")),
    };
    return {
      schema_version: MODERN_DOCUMENT_SMOKE_SCHEMA_VERSION,
      status: Object.values(checks).every(Boolean) ? "PASS" : "FAIL",
      checks,
      observations: { request_count: requests.length, screenshot_count: 3 },
    };
  } finally {
    if (browser) await browser.close();
    await server.close();
  }
}

function activeSession(input) {
  return {
    browser_session_schema_version: "oa_browser_session.v1",
    session_id: "session-uxm-s15",
    status: "ACTIVE",
    issuer: "nex-oa",
    audience: "nex-ae-api",
    token_use: "user",
    tenant_ref: { type: "oa.tenant", id: input.tenant_id },
    subject_ref: { type: "oa.user", id: "subject-uxm-s15" },
    scopes: input.requested_scopes,
    roles: ["employee"],
    issued_at: "2026-11-09T00:00:00Z",
    expires_at: "2026-11-09T01:00:00Z",
    metadata: {
      raw_token_included: false,
      service_token_included: false,
      password_included: false,
      browser_payload_owner_authoritative: false,
      claim_owner_authoritative: true,
    },
  };
}

function workspaceResponse() {
  return {
    workspace_schema_version: "ae_workspace_state.v1",
    workspace_id: "workspace-uxm-s15",
    chat_document_id: "conversation-uxm-s15",
    title: "내 업무 공간",
  };
}

function uploadHandoff() {
  return {
    upload_handoff_schema_version: "ae_upload_handoff.v1",
    upload_handoff_id: "handoff-uxm-s15",
    workspace_id: "workspace-uxm-s15",
    tenant_id: "tenant-uxm-s15",
    owner_user_id: "subject-uxm-s15",
    ownership_ref: { uploaded_by_subject_ref: { id: "subject-uxm-s15" } },
    status: "QUEUED",
    dedupe: { status: "CREATED" },
    source: { filename: "receipt.pdf", content_type: "application/pdf", size_bytes: 20, source_sha256: null },
    cx_document_ref: { document_id: "document-uxm-s15" },
    links: {},
  };
}

function uploadProgress() {
  return {
    progress_schema_version: "ae_upload_ingestion_progress.v1",
    upload_handoff_id: "handoff-uxm-s15",
    workspace_id: "workspace-uxm-s15",
    document_id: "document-uxm-s15",
    status: "INDEX_READY",
    progress_percent: 100,
    ingestion: { available: true, run_id: "run-uxm-s15", status: "SUCCEEDED", step_total: 4, step_completed: 4, attempt_count: 1, max_attempts: 4 },
    vector_index: { available: true, status: "READY", freshness_status: "READY", retrieval_usable: true, expected_vector_count: 2, actual_vector_count: 2 },
    failure: { present: false, error_code: null, retryable: false },
    metadata: { owner_scoped: true, raw_source_included: false, markdown_included: false, chunk_text_included: false, embedding_vector_included: false, provider_credentials_included: false },
  };
}

function documentItem() {
  return {
    document_library_schema_version: "ae_document_library_item.v1",
    workspace_id: "workspace-uxm-s15",
    tenant_id: "tenant-uxm-s15",
    owner_user_id: "subject-uxm-s15",
    document_id: "document-uxm-s15",
    upload_handoff_id: "handoff-uxm-s15",
    filename: "receipt.pdf",
    content_type: "application/pdf",
    size_bytes: 20,
    status: { dedupe_status: "CREATED", extraction_status: "SUCCEEDED", summary_status: "READY", summary_embedding_status: "READY" },
    summary: { summary_available: true, summary_preview: "출장비 영수증 요약", summary_char_count: 10 },
    metadata: { raw_source_stored_in_ae: false, raw_summary_stored_in_ae: false, cx_storage_redacted: true },
  };
}

function documentDetail() {
  return {
    projection_schema_version: "ae_document_detail_projection.v1",
    tenant_id: "tenant-uxm-s15",
    owner_user_id: "subject-uxm-s15",
    document: {
      document_id: "document-uxm-s15",
      filename: "receipt.pdf",
      status: { processing_status: "SUCCEEDED", extraction_status: "SUCCEEDED", summary_status: "READY" },
      summary: { summary_available: true },
    },
    cx: { source_kind: "ae-facade" },
  };
}

function retrievalResult() {
  return {
    retrieval_interaction_schema_version: "ae_retrieval_interaction.v1",
    retrieval_interaction_id: "retrieval-uxm-s15",
    chat_document_id: "conversation-uxm-s15",
    status: "COMPLETED",
    cx_status: "READY",
    purpose: "grounded_answer",
    retrieval: { evidence_count: 2, best_score: 0.92, confidence_bucket: "READY", warnings: [] },
  };
}

async function snapshot(page) {
  return page.evaluate(() => ({
    body: document.body.innerText,
    overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
  }));
}

async function json(route, status, body) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

export function formatSummary(evidence) {
  return evidence.status === "PASS"
    ? `modern_document_playwright_smoke=pass requests=${evidence.observations.request_count} screenshots=${evidence.observations.screenshot_count} checks=${Object.keys(evidence.checks).length}`
    : "modern_document_playwright_smoke=fail reason=checks_failed";
}

export async function main(argv = process.argv.slice(2), output = console.log) {
  try {
    const evidence = await runModernDocumentPlaywrightSmoke();
    output(argv.includes("--summary") ? formatSummary(evidence) : JSON.stringify(evidence, null, 2));
    return evidence.status === "PASS" ? 0 : 1;
  } catch (error) {
    output(`modern_document_playwright_smoke=fail error=${error?.constructor?.name ?? "Error"}`);
    return 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await main();
}
