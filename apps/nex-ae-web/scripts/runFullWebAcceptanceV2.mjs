#!/usr/bin/env node
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { runModernApprovalPlaywrightSmoke } from "./runModernApprovalPlaywrightSmoke.mjs";
import { runModernArtifactPlaywrightSmoke } from "./runModernArtifactPlaywrightSmoke.mjs";
import { runModernDocumentPlaywrightSmoke } from "./runModernDocumentPlaywrightSmoke.mjs";
import { runModernOperationsPlaywrightSmoke } from "./runModernOperationsPlaywrightSmoke.mjs";
import { runModernSecurityBoundaryPlaywrightSmoke } from "./runModernSecurityBoundaryPlaywrightSmoke.mjs";
import { runModernWorkspaceExecutionPlaywrightSmoke } from "./runModernWorkspaceExecutionPlaywrightSmoke.mjs";

export const FULL_WEB_ACCEPTANCE_V2_SCHEMA_VERSION = "ae_web_full_acceptance.uxm_s19.v1";
export const FULL_WEB_ACCEPTANCE_V2_JOURNEY_IDS = Object.freeze([
  "security-boundary",
  "workspace-execution",
  "approval-checkpoint",
  "document-retrieval",
  "artifact-result",
  "operations-isolation",
]);

const APP_ROOT = fileURLToPath(new URL("..", import.meta.url));
const DEFAULT_RECEIPT_PATH = resolve(
  APP_ROOT,
  "../../reports/uiux/full-web-acceptance-v2/receipt.json",
);

const JOURNEYS = Object.freeze([
  [FULL_WEB_ACCEPTANCE_V2_JOURNEY_IDS[0], runModernSecurityBoundaryPlaywrightSmoke],
  [FULL_WEB_ACCEPTANCE_V2_JOURNEY_IDS[1], runModernWorkspaceExecutionPlaywrightSmoke],
  [FULL_WEB_ACCEPTANCE_V2_JOURNEY_IDS[2], runModernApprovalPlaywrightSmoke],
  [FULL_WEB_ACCEPTANCE_V2_JOURNEY_IDS[3], runModernDocumentPlaywrightSmoke],
  [FULL_WEB_ACCEPTANCE_V2_JOURNEY_IDS[4], runModernArtifactPlaywrightSmoke],
  [FULL_WEB_ACCEPTANCE_V2_JOURNEY_IDS[5], runModernOperationsPlaywrightSmoke],
]);

export function buildFullWebAcceptanceV2Receipt(results) {
  const journeys = results.map(({ id, evidence }) => Object.freeze({
    id,
    status: evidence.status,
    checkCount: Object.keys(evidence.checks ?? {}).length,
    screenshotCount: Number(evidence.observations?.screenshot_count ?? 0),
  }));
  const failedJourneyIds = journeys.filter(item => item.status !== "PASS").map(item => item.id);
  return Object.freeze({
    schemaVersion: FULL_WEB_ACCEPTANCE_V2_SCHEMA_VERSION,
    status: failedJourneyIds.length === 0 && journeys.length === FULL_WEB_ACCEPTANCE_V2_JOURNEY_IDS.length
      ? "PASS"
      : "FAIL",
    viewports: Object.freeze({ desktop: "1440x900", mobile: "390x844" }),
    journeyCount: journeys.length,
    checkCount: journeys.reduce((total, item) => total + item.checkCount, 0),
    screenshotCount: journeys.reduce((total, item) => total + item.screenshotCount, 0),
    failedJourneyIds: Object.freeze(failedJourneyIds),
    journeys: Object.freeze(journeys),
  });
}

export async function runFullWebAcceptanceV2({ receiptPath = DEFAULT_RECEIPT_PATH } = {}) {
  const results = [];
  for (const [id, run] of JOURNEYS) {
    results.push({ id, evidence: await run() });
  }
  const receipt = buildFullWebAcceptanceV2Receipt(results);
  await mkdir(resolve(receiptPath, ".."), { recursive: true });
  await writeFile(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`, "utf8");
  return receipt;
}

export function formatSummary(receipt) {
  return receipt.status === "PASS"
    ? `full_web_acceptance_v2=pass journeys=${receipt.journeyCount} checks=${receipt.checkCount} screenshots=${receipt.screenshotCount}`
    : `full_web_acceptance_v2=fail failed=${receipt.failedJourneyIds.join(",") || "incomplete"}`;
}

export async function main(argv = process.argv.slice(2), output = console.log) {
  try {
    const receipt = await runFullWebAcceptanceV2();
    output(argv.includes("--summary") ? formatSummary(receipt) : JSON.stringify(receipt, null, 2));
    return receipt.status === "PASS" ? 0 : 1;
  } catch (error) {
    output(`full_web_acceptance_v2=fail error=${error?.constructor?.name ?? "Error"}`);
    return 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await main();
}
