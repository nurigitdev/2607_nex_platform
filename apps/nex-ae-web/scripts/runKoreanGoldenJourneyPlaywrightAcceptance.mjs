#!/usr/bin/env node
import { mkdir } from "node:fs/promises";
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  GOLDEN_JOURNEY_NON_OVERLAP_PAIRS,
  GOLDEN_JOURNEY_REGION_SELECTORS,
  GOLDEN_JOURNEY_VIEWPORTS,
  evaluateGoldenJourneyViewport,
  rectangleOverlapArea
} from "../src/goldenJourneyViewport.js";
import { PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV } from "./runCredentialLoginPlaywrightReadiness.mjs";

export const AE_WEB_KOREAN_GOLDEN_JOURNEY_PLAYWRIGHT_SCHEMA_VERSION =
  "ae_web_korean_golden_journey_playwright.v1";

export const ENV = Object.freeze({
  webUrl: "NEX_AE_WEB_GOLDEN_JOURNEY_WEB_URL",
  screenshotDir: "NEX_AE_WEB_GOLDEN_JOURNEY_SCREENSHOT_DIR",
  timeoutMs: "NEX_AE_WEB_GOLDEN_JOURNEY_TIMEOUT_MS"
});

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const DEFAULT_SCREENSHOT_DIR = "reports/quality/s139-playwright";
const DEFAULT_TIMEOUT_MS = 60_000;
const FORBIDDEN_EVIDENCE_FRAGMENTS = [
  "transient-browser-value",
  "deterministic-password",
  "Produce a grounded response",
  "MVP 착수 패키지 기준",
  "storage_ref",
  "database_url",
  "provider_url",
  "/data/nex-platform"
];

export async function runKoreanGoldenJourneyPlaywrightAcceptance({
  environ = process.env,
  importPlaywright = () => import("playwright"),
  viewportRunner = null
} = {}) {
  if (!environ[ENV.webUrl]) {
    return failureEvidence("required_env_missing", {
      missing_env: [ENV.webUrl],
      launch_attempted: false
    });
  }
  let browser = null;
  try {
    const screenshotDir = normalizeScreenshotDir(
      environ[ENV.screenshotDir] || DEFAULT_SCREENSHOT_DIR
    );
    const timeoutMs = normalizeTimeout(environ[ENV.timeoutMs]);
    let executeViewport = viewportRunner;
    if (!executeViewport) {
      const playwright = await importPlaywright();
      browser = await playwright.chromium.launch({
        headless: true,
        ...(environ[PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV]
          ? { executablePath: environ[PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV] }
          : {})
      });
      executeViewport = options => runViewport({ ...options, browser });
    }
    const viewports = [];
    for (const [viewportName, viewport] of Object.entries(
      GOLDEN_JOURNEY_VIEWPORTS
    )) {
      viewports.push(
        await executeViewport({
          viewportName,
          viewport,
          webUrl: environ[ENV.webUrl],
          screenshotDir,
          timeoutMs
        })
      );
    }
    const checks = {
      actual_chromium_launched: viewports.every(item => item.browserLaunched),
      desktop_passed: viewports.find(item => item.viewportName === "desktop")?.status === "PASS",
      mobile_passed: viewports.find(item => item.viewportName === "mobile")?.status === "PASS",
      nine_stage_journey_completed: viewports.every(
        item => item.journeyStageCount === 9
      ),
      korean_ui_confirmed: viewports.every(item => item.koreanUiConfirmed),
      login_upload_generation_visible: viewports.every(
        item => item.uiActionCount >= 3
      ),
      preview_download_visible: viewports.every(
        item => item.artifactActionCount === 2
      ),
      screenshots_captured: viewports.every(item => Boolean(item.screenshotRef)),
      page_errors_absent: viewports.every(item => item.pageErrorCount === 0),
      redacted_evidence: true
    };
    const evidence = {
      smoke_schema_version:
        AE_WEB_KOREAN_GOLDEN_JOURNEY_PLAYWRIGHT_SCHEMA_VERSION,
      status: Object.values(checks).every(Boolean) ? "PASS" : "FAIL",
      runner: {
        tool: "Playwright",
        browser: "chromium",
        headless: true,
        runtime: "deterministic_mock"
      },
      viewports: viewports.map(safeViewportEvidence),
      checks,
      issues: Object.entries(checks)
        .filter(([, passed]) => !passed)
        .map(([name]) => ({ category: "check_failed", subject: name })),
      redaction: {
        prompt_content_included: false,
        generated_content_included: false,
        source_content_included: false,
        credential_material_included: false,
        server_material_included: false
      }
    };
    assertEvidenceRedacted(evidence);
    return evidence;
  } catch (error) {
    const evidence = failureEvidence(error?.constructor?.name || "playwright_failed", {
      launch_attempted: Boolean(browser)
    });
    assertEvidenceRedacted(evidence);
    return evidence;
  } finally {
    if (browser) await browser.close();
  }
}

async function runViewport({
  browser,
  viewportName,
  viewport,
  webUrl,
  screenshotDir,
  timeoutMs
}) {
  const context = await browser.newContext({
    viewport,
    locale: "ko-KR",
    acceptDownloads: true
  });
  const page = await context.newPage();
  const pageErrorNames = [];
  let stage = "NAVIGATE";
  page.on("pageerror", error => pageErrorNames.push(error?.name || "Error"));
  try {
    await page.goto(webUrl, { waitUntil: "networkidle", timeout: timeoutMs });
    await page.waitForSelector("#main-workspace", { timeout: timeoutMs });
    const koreanUiConfirmed = await page.evaluate(() =>
      document.documentElement.lang === "ko" &&
      document.querySelector("h1")?.textContent?.includes("작업면") &&
      document.querySelector("#credential-login-title")?.textContent?.includes("로그인")
    );

    stage = "LOGIN";
    await page.fill("#credential-employee-id", "1001");
    await page.fill("#credential-password", "deterministic-password");
    await page.click("#credential-login-submit-button");
    await page.waitForSelector(
      "#credential-login-feedback[data-severity='success']",
      { timeout: timeoutMs }
    );

    stage = "UPLOAD";
    await page.setInputFiles("#upload-file-input", {
      name: "golden-reference.md",
      mimeType: "text/markdown",
      buffer: Buffer.from("# Golden reference\n\nDeterministic acceptance content.")
    });
    await page.fill("#upload-source-sha256", "a".repeat(64));
    await page.click("#upload-submit-button");
    await page.waitForSelector("#upload-feedback[data-severity='success']", {
      timeout: timeoutMs
    });

    stage = "GENERATION";
    const messageCount = await page.locator("#message-list .message.assistant").count();
    await page.fill("#prompt", "근거와 인용이 포함된 테스트 보고서를 작성해줘.");
    await page.click("#composer button[type='submit']");
    await page.waitForFunction(
      expected =>
        document.querySelectorAll("#message-list .message.assistant").length > expected,
      messageCount,
      { timeout: timeoutMs }
    );
    stage = "ARTIFACT_PREVIEW";
    const latestMessage = page.locator("#message-list .message.assistant").last();
    const previewAction = latestMessage.locator("[data-artifact-preview-route]").first();
    const downloadAction = latestMessage.locator("[data-artifact-download-route]").first();
    await previewAction.click();
    await page.waitForSelector(
      "#artifact-preview-content[data-status='PREVIEW_READY']",
      { timeout: timeoutMs }
    );
    stage = "ARTIFACT_DOWNLOAD";
    await downloadAction.click();
    await page.waitForSelector(
      "#artifact-preview-content[data-status='DOWNLOAD_READY']",
      { timeout: timeoutMs }
    );

    stage = "CORRELATED_JOURNEY";
    const deterministicJourney = await page.evaluate(async name => {
      const module = await import("./src/deterministicGoldenJourney.js");
      return module.runDeterministicGoldenJourney({
        journeyId: `journey-browser-${name}`
      });
    }, viewportName);

    stage = "LAYOUT";
    await page.keyboard.press("Tab");
    await page.locator(".skip-link").focus();
    await page.waitForFunction(
      () => document.activeElement?.matches(".skip-link:focus-visible") === true,
      null,
      { timeout: timeoutMs }
    );
    const snapshot = await collectLayoutSnapshot(page, viewportName, viewport);
    const layout = evaluateGoldenJourneyViewport(snapshot);
    stage = "SCREENSHOT";
    const screenshotRef = `${screenshotDir}/${viewportName}.png`;
    const screenshotPath = resolve(ROOT, screenshotRef);
    await mkdir(dirname(screenshotPath), { recursive: true });
    await page.screenshot({ path: screenshotPath, fullPage: false });
    const ui = await page.evaluate(() => ({
      loginSucceeded:
        document.querySelector("#credential-login-feedback")?.dataset.severity === "success",
      uploadSucceeded:
        document.querySelector("#upload-feedback")?.dataset.severity === "success",
      generationVisible:
        document.querySelectorAll("#message-list .message.assistant").length >= 2,
      previewReady:
        document.querySelector("#artifact-preview-content")?.dataset.status === "DOWNLOAD_READY",
      downloadReady:
        document.querySelector("#artifact-preview-summary")?.textContent.includes("DOWNLOAD_READY") === true,
      credentialFieldCleared:
        document.querySelector("#credential-password")?.value === ""
    }));
    const status =
      layout.status === "PASS" &&
      deterministicJourney.status === "PASS" &&
      Object.values(ui).every(Boolean) &&
      pageErrorNames.length === 0
        ? "PASS"
        : "FAIL";
    return {
      viewportName,
      status,
      browserLaunched: true,
      koreanUiConfirmed: Boolean(koreanUiConfirmed),
      journeyStageCount:
        deterministicJourney.summary?.completedStageCount || 0,
      uiActionCount: [ui.loginSucceeded, ui.uploadSucceeded, ui.generationVisible]
        .filter(Boolean).length,
      artifactActionCount: [ui.previewReady, ui.downloadReady].filter(Boolean).length,
      credentialFieldCleared: ui.credentialFieldCleared,
      pageErrorCount: pageErrorNames.length,
      layout,
      screenshotRef
    };
  } catch (error) {
    return {
      viewportName,
      status: "FAIL",
      browserLaunched: true,
      koreanUiConfirmed: false,
      journeyStageCount: 0,
      uiActionCount: 0,
      artifactActionCount: 0,
      credentialFieldCleared: false,
      pageErrorCount: pageErrorNames.length,
      layout: null,
      screenshotRef: null,
      failureStage: stage,
      failureType: error?.constructor?.name || "Error"
    };
  } finally {
    await context.close();
  }
}

async function collectLayoutSnapshot(page, viewportName, viewport) {
  const base = await page.evaluate(
    ({ regionSelectors, pairs }) => {
      const regionRects = {};
      const regions = Object.entries(regionSelectors).map(([name, selector]) => {
        const element = document.querySelector(selector);
        const rect = element?.getBoundingClientRect();
        if (rect) {
          regionRects[name] = {
            x: rect.x,
            y: rect.y,
            width: rect.width,
            height: rect.height
          };
        }
        return {
          name,
          present: Boolean(element),
          width: rect?.width || 0,
          height: rect?.height || 0
        };
      });
      const controls = [...document.querySelectorAll("a[href], button, input, select")]
        .filter(element => {
          const style = getComputedStyle(element);
          const rect = element.getBoundingClientRect();
          return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
        })
        .map(element => {
          const ownRect = element.getBoundingClientRect();
          const target = element.matches("input[type='checkbox'], input[type='radio']")
            ? element.closest("label") || element
            : element;
          const targetRect = target.getBoundingClientRect();
          const labelled = element.labels ? [...element.labels].map(label => label.textContent || "").join(" ") : "";
          const name = element.getAttribute("aria-label") || labelled || element.textContent || element.getAttribute("title") || "";
          return {
            visible: ownRect.width > 0 && ownRect.height > 0,
            namePresent: Boolean(name.trim()),
            targetWidth: targetRect.width,
            targetHeight: targetRect.height
          };
        });
      const active = document.activeElement;
      const activeStyle = active ? getComputedStyle(active) : null;
      return {
        htmlLang: document.documentElement.lang,
        mainLandmarkCount: document.querySelectorAll("main").length,
        primaryHeadingCount: document.querySelectorAll("h1").length,
        documentWidth: document.documentElement.scrollWidth,
        regions,
        controls,
        focusIndicatorVisible: Boolean(
          active?.matches(".skip-link:focus-visible") &&
          activeStyle &&
          activeStyle.outlineStyle !== "none" &&
          Number.parseFloat(activeStyle.outlineWidth) > 0
        ),
        regionRects,
        pairs
      };
    },
    {
      regionSelectors: GOLDEN_JOURNEY_REGION_SELECTORS,
      pairs: GOLDEN_JOURNEY_NON_OVERLAP_PAIRS
    }
  );
  return {
    viewportName,
    viewportWidth: viewport.width,
    viewportHeight: viewport.height,
    htmlLang: base.htmlLang,
    mainLandmarkCount: base.mainLandmarkCount,
    primaryHeadingCount: base.primaryHeadingCount,
    documentWidth: base.documentWidth,
    regions: base.regions,
    controls: base.controls,
    focusIndicatorVisible: base.focusIndicatorVisible,
    overlapPairs: GOLDEN_JOURNEY_NON_OVERLAP_PAIRS.map(([first, second]) => ({
      first,
      second,
      overlapArea: rectangleOverlapArea(
        base.regionRects[first],
        base.regionRects[second]
      )
    }))
  };
}

function safeViewportEvidence(item) {
  return {
    viewport_name: item.viewportName,
    status: item.status,
    browser_launched: Boolean(item.browserLaunched),
    korean_ui_confirmed: Boolean(item.koreanUiConfirmed),
    journey_stage_count: item.journeyStageCount || 0,
    ui_action_count: item.uiActionCount || 0,
    artifact_action_count: item.artifactActionCount || 0,
    credential_field_cleared: Boolean(item.credentialFieldCleared),
    page_error_count: item.pageErrorCount || 0,
    layout: item.layout,
    screenshot_ref: item.screenshotRef || null,
    failure_stage: item.failureStage || null,
    failure_type: item.failureType || null
  };
}

function normalizeScreenshotDir(value) {
  const normalized = String(value || "").replaceAll("\\", "/").replace(/\/+$/, "");
  if (
    !normalized.startsWith("reports/quality/") ||
    normalized.includes("..") ||
    !/^[A-Za-z0-9_./-]+$/.test(normalized)
  ) {
    throw new TypeError("golden journey screenshot directory is invalid");
  }
  return relative(ROOT, resolve(ROOT, normalized)).replaceAll("\\", "/");
}

function normalizeTimeout(value) {
  const parsed = Number(value || DEFAULT_TIMEOUT_MS);
  if (!Number.isInteger(parsed) || parsed < 1_000 || parsed > 300_000) {
    throw new TypeError("golden journey timeout is invalid");
  }
  return parsed;
}

function failureEvidence(reason, details) {
  return {
    smoke_schema_version:
      AE_WEB_KOREAN_GOLDEN_JOURNEY_PLAYWRIGHT_SCHEMA_VERSION,
    status: "FAIL",
    runner: {
      tool: "Playwright",
      browser: "chromium",
      headless: true,
      runtime: "deterministic_mock"
    },
    viewports: [],
    checks: { protected_execution_ready: false, redacted_evidence: true },
    issues: [{ category: reason, ...details }],
    redaction: {
      prompt_content_included: false,
      generated_content_included: false,
      source_content_included: false,
      credential_material_included: false,
      server_material_included: false
    }
  };
}

export function assertEvidenceRedacted(evidence) {
  const serialized = JSON.stringify(evidence);
  if (FORBIDDEN_EVIDENCE_FRAGMENTS.some(fragment => serialized.includes(fragment))) {
    throw new TypeError("golden journey Playwright evidence contains private material");
  }
  return evidence;
}

export function summaryLine(evidence) {
  return [
    `ae_web_korean_golden_journey_playwright=${evidence.status.toLowerCase()}`,
    `viewports=${evidence.viewports?.length || 0}`,
    `stages=${evidence.viewports?.[0]?.journey_stage_count || 0}`,
    `issues=${evidence.issues?.length || 0}`
  ].join(" ");
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const summary = process.argv.includes("--summary");
  const evidence = await runKoreanGoldenJourneyPlaywrightAcceptance();
  console.log(summary ? summaryLine(evidence) : JSON.stringify(evidence, null, 2));
  process.exitCode = evidence.status === "PASS" ? 0 : 1;
}
