#!/usr/bin/env node
import { pathToFileURL } from "node:url";

import {
  runP8DemoS11ChairmanGoldenJourney,
  runP8DemoS11PostRestartRecovery
} from "./runP8DemoS11ChairmanGoldenJourney.mjs";


export const CANONICAL_PLATFORM_GOLDEN_JOURNEY_SCHEMA_VERSION =
  "canonical_platform_golden_journey_playwright.v1";

const ENV_ALIASES = {
  NEX_CANONICAL_PLATFORM_GOLDEN_WEB_URL: "NEX_P8_DEMO_S11_WEB_URL",
  NEX_CANONICAL_PLATFORM_GOLDEN_TENANT_ID: "NEX_P8_DEMO_S11_TENANT_ID",
  NEX_CANONICAL_PLATFORM_GOLDEN_REQUESTER_EMPLOYEE_ID:
    "NEX_P8_DEMO_S11_REQUESTER_EMPLOYEE_ID",
  NEX_CANONICAL_PLATFORM_GOLDEN_REQUESTER_PASSWORD:
    "NEX_P8_DEMO_S11_REQUESTER_PASSWORD",
  NEX_CANONICAL_PLATFORM_GOLDEN_APPROVER_EMPLOYEE_ID:
    "NEX_P8_DEMO_S11_APPROVER_EMPLOYEE_ID",
  NEX_CANONICAL_PLATFORM_GOLDEN_APPROVER_PASSWORD:
    "NEX_P8_DEMO_S11_APPROVER_PASSWORD",
  NEX_CANONICAL_PLATFORM_GOLDEN_PROMPT: "NEX_P8_DEMO_S11_PROMPT",
  NEX_CANONICAL_PLATFORM_GOLDEN_RECOVERY_INTERACTION_ID:
    "NEX_P8_DEMO_S11_RECOVERY_INTERACTION_ID",
  NEX_CANONICAL_PLATFORM_GOLDEN_SCREENSHOT_DIR:
    "NEX_P8_DEMO_S11_SCREENSHOT_DIR",
  NEX_CANONICAL_PLATFORM_GOLDEN_TIMEOUT_MS: "NEX_P8_DEMO_S11_TIMEOUT_MS"
};

export function canonicalGoldenJourneyEnvironment(environ = process.env) {
  const translated = { ...environ };
  for (const [canonical, legacy] of Object.entries(ENV_ALIASES)) {
    if (translated[canonical] && !translated[legacy]) {
      translated[legacy] = translated[canonical];
    }
  }
  return translated;
}

export async function runCanonicalPlatformGoldenJourney({
  environ = process.env,
  importPlaywright
} = {}) {
  return runP8DemoS11ChairmanGoldenJourney({
    environ: canonicalGoldenJourneyEnvironment(environ),
    importPlaywright
  });
}

export async function runCanonicalPlatformPostRestartRecovery({
  environ = process.env,
  importPlaywright
} = {}) {
  return runP8DemoS11PostRestartRecovery({
    environ: canonicalGoldenJourneyEnvironment(environ),
    importPlaywright
  });
}

export async function main(argv = process.argv.slice(2), output = console.log) {
  const evidence = argv.includes("--recovery")
    ? await runCanonicalPlatformPostRestartRecovery()
    : await runCanonicalPlatformGoldenJourney();
  output(JSON.stringify(evidence));
  return evidence.status === "PASS" ? 0 : 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await main();
}
