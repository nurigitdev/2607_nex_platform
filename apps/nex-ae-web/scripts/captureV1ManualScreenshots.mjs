#!/usr/bin/env node
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, relative, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

import { createAeWebServer } from "./serve.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const OUTPUT_DIR = resolve(ROOT, "docs/releases/v1.0/assets/screenshots");
const SOURCE_TAG = "v1.0";
const VIEWPORT = Object.freeze({ width: 1600, height: 1000 });
const FIXED_NOW = "2026-10-09T08:00:00.000Z";

const CAPTURES = Object.freeze([
  ["01_workspace_login.png", "NeX AE Korean workspace and employee login"],
  ["02_service_runtime.png", "Service readiness and browser runtime diagnostics"],
  ["03_document_upload.png", "Owner-scoped document upload"],
  ["04_grounded_chat.png", "Grounded chat result and citation-quality surface"],
  ["05_generation_timeline.png", "Generation progress timeline"],
  ["06_artifact_preview.png", "Generated artifact preview and download state"],
  ["07_ag_audit.png", "AG audit correlation summary"]
]);

export async function captureV1ManualScreenshots({ root = ROOT } = {}) {
  const sourceRevision = git(root, ["rev-parse", `${SOURCE_TAG}^{commit}`]);
  assertV1UiUnchanged(root);
  const sourceDate = git(root, ["show", "-s", "--format=%cI", `${SOURCE_TAG}^{commit}`]);
  const outputDir = resolve(root, relative(ROOT, OUTPUT_DIR));
  await mkdir(outputDir, { recursive: true });

  const server = createAeWebServer();
  await new Promise((resolveListen, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolveListen);
  });
  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("AE Web documentation server did not expose a TCP port");
  }

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: VIEWPORT,
    locale: "ko-KR",
    timezoneId: "Asia/Seoul",
    colorScheme: "light",
    reducedMotion: "reduce",
    deviceScaleFactor: 1
  });
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error?.name || "Error"));
  await page.route(/http:\/\/127\.0\.0\.1:810[1-5]\/(health|ready|version)/, async route => {
    const endpoint = new URL(route.request().url()).pathname;
    const body = endpoint === "/health"
      ? { health_status: "HEALTHY" }
      : endpoint === "/ready"
        ? { readiness_status: "READY" }
        : { version: "v1.0" };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.addInitScript(fixedNow => {
    const NativeDate = Date;
    const fixedEpoch = NativeDate.parse(fixedNow);
    globalThis.Date = class extends NativeDate {
      constructor(...args) {
        super(...(args.length ? args : [fixedEpoch]));
      }

      static now() {
        return fixedEpoch;
      }
    };
  }, FIXED_NOW);

  const url = `http://127.0.0.1:${address.port}/`;
  try {
    await page.goto(url, { waitUntil: "networkidle" });
    await page.waitForSelector("#main-workspace");
    await page.addStyleTag({
      content: "*{animation:none!important;transition:none!important}body{caret-color:transparent!important}"
    });
    await capturePage(page, outputDir, CAPTURES[0][0]);

    await page.fill("#credential-employee-id", "1001");
    await page.fill("#credential-password", "documentation-only-password");
    await page.click("#credential-login-submit-button");
    await page.waitForSelector("#credential-login-feedback[data-severity='success']");
    await captureElement(page, outputDir, CAPTURES[1][0], "#runtime-diagnostics-panel", {
      hiddenSelectors: ["#runtime-diagnostics-preview"]
    });

    await page.setInputFiles("#upload-file-input", {
      name: "v1-user-guide-reference.md",
      mimeType: "text/markdown",
      buffer: Buffer.from("# NeX Platform v1.0\n\nSynthetic documentation fixture.\n")
    });
    await page.fill("#upload-source-sha256", "a".repeat(64));
    await page.click("#upload-submit-button");
    await page.waitForSelector("#upload-feedback[data-severity='success']");
    await captureElement(page, outputDir, CAPTURES[2][0], "#upload-surface-panel", {
      hiddenSelectors: ["#upload-payload-preview"]
    });

    const assistantCount = await page.locator("#message-list .message.assistant").count();
    await page.fill("#prompt", "근거와 인용이 포함된 테스트 보고서를 작성해줘.");
    await page.click("#composer button[type='submit']");
    await page.waitForFunction(
      expected => document.querySelectorAll("#message-list .message.assistant").length > expected,
      assistantCount
    );
    await captureElement(
      page,
      outputDir,
      CAPTURES[3][0],
      "#message-list .message.assistant:last-child"
    );
    await captureElement(page, outputDir, CAPTURES[4][0], "#golden-timeline");

    const latestMessage = page.locator("#message-list .message.assistant").last();
    await latestMessage.locator("[data-artifact-preview-route]").first().click();
    await page.waitForSelector("#artifact-preview-content[data-status='PREVIEW_READY']");
    await latestMessage.locator("[data-artifact-download-route]").first().click();
    await page.waitForSelector("#artifact-preview-content[data-status='DOWNLOAD_READY']");
    await captureElement(page, outputDir, CAPTURES[5][0], "#artifact-panel", {
      hiddenSelectors: [
        ".artifact-library-toolbar",
        "#artifact-library-feedback",
        "#artifact-library-summary",
        "#artifact-library-list",
        "#artifact-summary",
        "#artifact-version-feedback",
        "#artifact-version-summary",
        "#artifact-version-list"
      ]
    });
    await captureElement(page, outputDir, CAPTURES[6][0], "#audit-panel");
  } finally {
    await context.close();
    await browser.close();
    await new Promise(resolveClose => server.close(resolveClose));
  }

  if (pageErrors.length) {
    throw new Error(`AE Web emitted page errors: ${pageErrors.join(",")}`);
  }
  const captures = [];
  for (const [filename, description] of CAPTURES) {
    const path = resolve(outputDir, filename);
    const bytes = await readFile(path);
    captures.push({
      filename,
      description,
      sha256: createHash("sha256").update(bytes).digest("hex"),
      size_bytes: bytes.length
    });
  }
  const manifest = {
    schema_version: "nex_v1_manual_screenshots.v1",
    source_tag: SOURCE_TAG,
    source_revision: sourceRevision,
    source_date: sourceDate,
    runtime: "deterministic_mock",
    browser: "chromium",
    locale: "ko-KR",
    viewport: VIEWPORT,
    private_data_included: false,
    capture_count: captures.length,
    captures
  };
  await writeFile(
    resolve(outputDir, "manifest.json"),
    `${JSON.stringify(manifest, null, 2)}\n`,
    "utf8"
  );
  return manifest;
}

async function capturePage(page, outputDir, filename) {
  await page.screenshot({
    path: resolve(outputDir, filename),
    fullPage: false,
    animations: "disabled",
    caret: "hide"
  });
}

async function captureElement(
  page,
  outputDir,
  filename,
  selector,
  { hiddenSelectors = [] } = {}
) {
  const locator = page.locator(selector);
  const style = hiddenSelectors.length
    ? await page.addStyleTag({
        content: `${hiddenSelectors.join(",")} { display: none !important; }`
      })
    : null;
  try {
    if (!(await locator.isVisible())) {
      throw new Error(`documentation capture target is not visible: ${selector}`);
    }
    await locator.screenshot({
      path: resolve(outputDir, filename),
      animations: "disabled",
      caret: "hide"
    });
  } finally {
    await style?.evaluate(element => element.remove());
  }
}

function assertV1UiUnchanged(root) {
  const result = spawnSync(
    "git",
    ["diff", "--quiet", SOURCE_TAG, "--", "apps/nex-ae-web/index.html", "apps/nex-ae-web/src"],
    { cwd: root, encoding: "utf8" }
  );
  if (result.status !== 0) {
    throw new Error("AE Web runtime files differ from the immutable v1.0 tag");
  }
}

function git(root, args) {
  const result = spawnSync("git", args, { cwd: root, encoding: "utf8" });
  if (result.status !== 0) {
    throw new Error(`git ${args[0]} failed`);
  }
  return result.stdout.trim();
}

export function summaryLine(manifest) {
  return [
    "v1_manual_screenshots=pass",
    `tag=${manifest.source_tag}`,
    `revision=${manifest.source_revision.slice(0, 8)}`,
    `captures=${manifest.capture_count}`,
    `private_data=${manifest.private_data_included}`
  ].join(" ");
}

if (import.meta.url === `file://${process.argv[1]}`) {
  try {
    const manifest = await captureV1ManualScreenshots();
    console.log(
      process.argv.includes("--summary")
        ? summaryLine(manifest)
        : JSON.stringify(manifest, null, 2)
    );
  } catch (error) {
    console.error(`v1_manual_screenshots=fail reason=${error?.message || "unknown"}`);
    process.exitCode = 1;
  }
}
