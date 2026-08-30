#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  renderArtifactCard
} from "../src/artifactCard.js";
import {
  buildArtifactDownloadFormatSelector,
  renderArtifactDownloadFormatSelector
} from "../src/artifactDownloadFormatSelector.js";

export const AE_WEB_ARTIFACT_DELIVERY_ACCESSIBILITY_SMOKE_SCHEMA_VERSION =
  "ae_web_artifact_delivery_accessibility_smoke.v1";

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const APP_DIR = resolve(SCRIPT_DIR, "..");
const ROOT_DIR = resolve(APP_DIR, "../..");

const FORBIDDEN_EVIDENCE_FRAGMENTS = [
  "content_" + "base64",
  "content_" + "text",
  "database_" + "url",
  "provider_" + "url",
  "service_" + "token",
  "storage_" + "ref",
  "storage_" + "path",
  "/data/" + "nex-platform",
  ["ed6", "@", "c496em"].join(""),
  ["nuri", "1004"].join("")
];

export function runArtifactDeliveryAccessibilitySmoke({
  stylesSource = readFileSync(resolve(APP_DIR, "src/styles.css"), "utf-8"),
  qualityGateSource = readFileSync(
    resolve(ROOT_DIR, "scripts/quality/run_quality_gate.sh"),
    "utf-8"
  )
} = {}) {
  const artifactRef = multiFormatArtifactRef();
  const cardHtml = renderArtifactCard(artifactRef);
  const selector = buildArtifactDownloadFormatSelector({
    artifactRef,
    selectedFormat: "PDF",
    clientMode: "fetch"
  });
  const selectorView = renderArtifactDownloadFormatSelector(selector);
  const combinedHtml = `${cardHtml}\n${selectorView.html}`;
  const downloadRoutes = extractAttributeValues(combinedHtml, "data-artifact-download-route");
  const selectedControls = countMatches(combinedHtml, /aria-pressed="true"/g);
  const disabledControls = countMatches(
    combinedHtml,
    /aria-disabled="true"[\s\S]*?disabled/g
  );
  const checks = {
    artifact_card_region_label_present: combinedHtml.includes(
      'aria-label="연결된 아티팩트"'
    ),
    selector_region_label_present: combinedHtml.includes(
      'aria-label="아티팩트 다운로드 포맷"'
    ),
    preview_anchor_keyboard_reachable:
      /<a[\s\S]*href="\/api\/v1\/artifact-files\/file-md-0438\/preview"[\s\S]*data-artifact-preview-route/.test(
        combinedHtml
      ),
    download_anchor_keyboard_reachable:
      downloadRoutes.length >= 4 &&
      downloadRoutes.every(route => route.startsWith("/api/v1/artifact-files/")),
    selector_selected_state_visible: selectedControls >= 1,
    selector_disabled_state_visible: disabledControls >= 1,
    browser_click_path_shared: qualityGateSource.includes(
      "runArtifactDeliveryAccessibilitySmoke.mjs"
    ),
    focus_visible_style_present: stylesSource.includes(":focus-visible"),
    raw_payload_absent: !/contentBase64|content_text|storage_ref|database_url|provider_url|service_token|\/data\/nex-platform/i.test(
      combinedHtml
    ),
    rendered_routes_same_origin: downloadRoutes.every(route => route.startsWith("/api/"))
  };
  const evidence = {
    smoke_schema_version:
      AE_WEB_ARTIFACT_DELIVERY_ACCESSIBILITY_SMOKE_SCHEMA_VERSION,
    status: Object.values(checks).every(Boolean) ? "PASS" : "FAIL",
    runner: {
      mode: "deterministic_render",
      live_network_used: false,
      postgresql_used: false
    },
    observations: {
      download_route_count: downloadRoutes.length,
      selected_control_count: selectedControls,
      disabled_control_count: disabledControls,
      html_length: combinedHtml.length
    },
    checks,
    redaction: {
      raw_download_body_in_evidence: false,
      raw_base64_payload_in_evidence: false,
      server_material_in_evidence: false
    }
  };
  assertArtifactDeliveryAccessibilitySmokeRedacted(evidence);
  return evidence;
}

export function formatSummary(evidence) {
  if (evidence.status === "PASS") {
    return (
      "ae_web_artifact_delivery_accessibility_smoke=pass " +
      `routes=${evidence.observations.download_route_count} ` +
      `selected=${evidence.observations.selected_control_count} ` +
      `disabled=${evidence.observations.disabled_control_count}`
    );
  }
  return "ae_web_artifact_delivery_accessibility_smoke=fail reason=checks_failed";
}

export function assertArtifactDeliveryAccessibilitySmokeRedacted(evidence) {
  const serialized = JSON.stringify(evidence);
  for (const fragment of FORBIDDEN_EVIDENCE_FRAGMENTS) {
    if (serialized.includes(fragment)) {
      throw new Error(
        "AE Web artifact delivery accessibility smoke leaked server material"
      );
    }
  }
}

export async function main(argv = process.argv.slice(2), output = console.log) {
  const summary = argv.includes("--summary");
  try {
    const evidence = runArtifactDeliveryAccessibilitySmoke();
    output(summary ? formatSummary(evidence) : JSON.stringify(evidence, null, 2));
    return evidence.status === "PASS" ? 0 : 1;
  } catch (error) {
    output(
      "ae_web_artifact_delivery_accessibility_smoke=fail " +
      `error=${error?.constructor?.name || "Error"}`
    );
    return 1;
  }
}

function multiFormatArtifactRef() {
  return {
    artifactId: "artifact-0438",
    artifactVersionId: "version-0438",
    displayTitle: "Delivery accessibility report",
    artifactType: "generated_document",
    artifactStatus: "READY",
    primaryFormat: "PDF",
    availableFormats: ["MD", "DOCX", "PDF"],
    previewRoute: "/api/v1/artifact-files/file-md-0438/preview",
    downloadRoutes: {
      MD: "/api/v1/artifact-files/file-md-0438/download",
      PDF: "/api/v1/artifact-files/file-pdf-0438/download"
    },
    sourceGenerationId: "cx-generation-0438",
    qualitySummary: {
      citationStatus: "VALIDATED",
      evidenceRefCount: 2
    },
    actions: ["preview", "download_md", "download_pdf"]
  };
}

function extractAttributeValues(html, attributeName) {
  const pattern = new RegExp(`${attributeName}="([^"]+)"`, "g");
  return [...html.matchAll(pattern)].map(match => match[1]);
}

function countMatches(text, pattern) {
  return [...text.matchAll(pattern)].length;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  process.exitCode = await main();
}
