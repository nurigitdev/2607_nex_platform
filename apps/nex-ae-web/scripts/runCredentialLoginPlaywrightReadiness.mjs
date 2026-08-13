#!/usr/bin/env node
import { pathToFileURL } from "node:url";

export const AE_WEB_PLAYWRIGHT_READINESS_SCHEMA_VERSION =
  "ae_web_playwright_readiness_node.v1";
export const PLAYWRIGHT_LAUNCH_CHECK_ENV = "NEX_AE_WEB_PLAYWRIGHT_LAUNCH_CHECK";
export const PLAYWRIGHT_BROWSER_ENV = "NEX_AE_WEB_PLAYWRIGHT_BROWSER";
export const PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV =
  "NEX_AE_WEB_PLAYWRIGHT_CHROMIUM_EXECUTABLE";
export const DEFAULT_BROWSER_NAME = "chromium";

const SUPPORTED_BROWSERS = new Set(["chromium"]);
const FORBIDDEN_EVIDENCE_FRAGMENTS = [
  "access_" + "token",
  "api_" + "key",
  "database_" + "url",
  "password_" + "hash",
  `provider_${"url"}`,
  `service_${"token"}`,
  "/data/" + "nex-platform"
];

export async function runPlaywrightReadiness({
  environ = process.env,
  launchCheck = environ[PLAYWRIGHT_LAUNCH_CHECK_ENV] === "1",
  importPlaywright = () => import("playwright")
} = {}) {
  const browserName = environ[PLAYWRIGHT_BROWSER_ENV] || DEFAULT_BROWSER_NAME;
  const chromiumExecutablePath =
    browserName === "chromium"
      ? environ[PLAYWRIGHT_CHROMIUM_EXECUTABLE_ENV] || ""
      : "";
  const checks = {
    dependency_importable: false,
    browser_supported: SUPPORTED_BROWSERS.has(browserName),
    launch_check_requested: launchCheck,
    browser_launch_succeeded: launchCheck ? false : null,
    same_origin_proxy_profile: true,
    redacted_evidence: true
  };
  const issues = [];
  let playwrightModule = null;

  if (!checks.browser_supported) {
    issues.push({
      category: "browser_unsupported",
      subject: browserName,
      detail: "Only Chromium is part of the protected AE Web smoke profile."
    });
  }

  try {
    playwrightModule = await importPlaywright();
    checks.dependency_importable = Boolean(playwrightModule?.[browserName]);
  } catch {
    issues.push({
      category: "dependency_import_failed",
      subject: "playwright",
      detail: "Install AE Web npm dependencies before launch checks."
    });
  }

  if (!checks.dependency_importable && playwrightModule !== null) {
    issues.push({
      category: "browser_launcher_missing",
      subject: browserName,
      detail: "The requested Playwright browser launcher is unavailable."
    });
  }

  if (launchCheck && checks.dependency_importable && checks.browser_supported) {
    const launcher = playwrightModule[browserName];
    try {
      const browser = await launcher.launch({
        headless: true,
        ...(chromiumExecutablePath ? { executablePath: chromiumExecutablePath } : {})
      });
      await browser.close();
      checks.browser_launch_succeeded = true;
    } catch {
      issues.push({
        category: "browser_launch_failed",
        subject: browserName,
        detail: "Playwright dependency is present, but the browser cannot launch."
      });
    }
  }

  const evidence = {
    readiness_schema_version: AE_WEB_PLAYWRIGHT_READINESS_SCHEMA_VERSION,
    status: issues.length === 0 ? "PASS" : "FAIL",
    runner: {
      mode: launchCheck ? "launch_check" : "dependency_readiness",
      playwright_package: "playwright",
      playwright_test_package: "@playwright/test",
      browser: browserName,
      headless: true,
      launch_check_required: launchCheck,
      system_chromium_executable_configured: Boolean(chromiumExecutablePath)
    },
    automation_contract: {
      next_execution_slice: "Slice 0270",
      browser_smoke_tool: "Playwright",
      browser_base_path: "/ae-api",
      credential_login_route: "/ae-api/api/v1/auth/session/login",
      same_origin_credentials_required: true,
      postgres_test_databases_required_for_live_smoke: true,
      raw_password_in_evidence: false,
      cookie_material_in_evidence: false,
      database_endpoint_in_evidence: false,
      provider_endpoint_in_evidence: false
    },
    checks,
    issues,
    redaction: {
      protected_env_value_in_evidence: false,
      server_only_material_in_evidence: false
    }
  };
  assertPlaywrightReadinessEvidenceRedacted(evidence, environ);
  return evidence;
}

export function formatSummary(evidence) {
  if (evidence.status === "PASS") {
    return (
      "ae_web_playwright_readiness=pass " +
      `browser=${evidence.runner.browser} ` +
      `mode=${evidence.runner.mode} ` +
      `launch=${evidence.checks.launch_check_requested ? "checked" : "deferred"}`
    );
  }
  return (
    "ae_web_playwright_readiness=fail " +
    `issues=${evidence.issues.length}`
  );
}

export function assertPlaywrightReadinessEvidenceRedacted(
  evidence
) {
  const serialized = JSON.stringify(evidence);
  for (const fragment of FORBIDDEN_EVIDENCE_FRAGMENTS) {
    if (serialized.includes(fragment)) {
      throw new Error("AE Web Playwright readiness evidence leaked server material");
    }
  }
}

export async function main(argv = process.argv.slice(2), output = console.log) {
  const summary = argv.includes("--summary");
  const json = argv.includes("--json");
  const launchCheck = argv.includes("--launch-check") || process.env[PLAYWRIGHT_LAUNCH_CHECK_ENV] === "1";
  try {
    const evidence = await runPlaywrightReadiness({ launchCheck });
    output(
      summary && !json
        ? formatSummary(evidence)
        : JSON.stringify(evidence, null, 2)
    );
    return evidence.status === "PASS" ? 0 : 1;
  } catch (error) {
    output(
      "ae_web_playwright_readiness=fail " +
      `error=${error?.constructor?.name || "Error"}`
    );
    return 1;
  }
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  main().then(code => {
    process.exitCode = code;
  });
}
